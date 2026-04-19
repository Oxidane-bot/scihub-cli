"""
Sci-Hub source implementation.
"""

import time

from ..core.doi_processor import DOIProcessor
from ..core.downloader import FileDownloader
from ..core.mirror_manager import MirrorManager
from ..core.parser import ContentParser
from ..utils.logging import get_logger
from .base import PaperSource

logger = get_logger(__name__)


class SciHubSource(PaperSource):
    """Sci-Hub paper source."""

    _FAST_FAIL_MAX_MIRRORS = 2
    _FAST_FAIL_TOTAL_BUDGET_SECONDS = 12.0
    _FAST_FAIL_PAGE_TIMEOUT_SECONDS = 5.0
    _FAST_FAIL_RESCUE_MAX_MIRRORS = 4
    _FAST_FAIL_RESCUE_TOTAL_BUDGET_SECONDS = 24.0
    _FAST_FAIL_RESCUE_PAGE_TIMEOUT_SECONDS = 8.0
    _FAST_FAIL_RESCUE_PREFIXES = (
        "10.1002/",
        "10.1016/",
        "10.1057/",
        "10.1080/",
        "10.1108/",
        "10.1115/",
        "10.1177/",
        "10.2501/",
    )
    _FAST_FAIL_RESCUE_MIRROR_ORDER_HINTS = (
        "sci-hub.vg",
        "sci-hub.mk",
        "sci-hub.ren",
        "sci-hub.ee",
    )
    _BLOCKED_COOLDOWN_SECONDS = 600.0
    _FAST_FAIL_BLOCKED_COOLDOWN_SECONDS = 120.0

    def __init__(
        self,
        mirror_manager: MirrorManager,
        parser: ContentParser,
        doi_processor: DOIProcessor,
        downloader: FileDownloader,
    ):
        """
        Initialize Sci-Hub source.

        Args:
            mirror_manager: Mirror management instance
            parser: HTML parser instance
            doi_processor: DOI processor instance
            downloader: File downloader instance
        """
        self.mirror_manager = mirror_manager
        self.parser = parser
        self.doi_processor = doi_processor
        self.downloader = downloader
        self._blocked_until = 0.0

    @property
    def name(self) -> str:
        return "Sci-Hub"

    def can_handle(self, identifier: str) -> bool:
        """Sci-Hub is only attempted for DOIs (avoids unnecessary requests for non-DOI IDs)."""
        return identifier.startswith("10.")

    def get_pdf_url(self, doi: str) -> str | None:
        """
        Get PDF download URL from Sci-Hub.

        Args:
            doi: The DOI to look up

        Returns:
            PDF URL if found, None otherwise
        """
        try:
            cooldown_seconds = self._BLOCKED_COOLDOWN_SECONDS
            fast_fail = bool(getattr(self.downloader, "fast_fail", False))
            if fast_fail and cooldown_seconds > 0:
                cooldown_seconds = min(cooldown_seconds, self._FAST_FAIL_BLOCKED_COOLDOWN_SECONDS)

            if cooldown_seconds > 0:
                now = time.monotonic()
                if now < self._blocked_until:
                    remaining = int(self._blocked_until - now)
                    logger.info(
                        f"[Sci-Hub] Skipping mirror attempts (cooldown {remaining}s remaining)"
                    )
                    return None
            if fast_fail and self._should_skip_fast_fail_for_low_confidence_doi(doi):
                logger.info(f"[Sci-Hub] Fast-fail skip low-confidence DOI pattern: {doi}")
                return None
            fast_fail_rescue = fast_fail and self._is_fast_fail_rescue_doi(doi)
            total_budget = (
                self._FAST_FAIL_RESCUE_TOTAL_BUDGET_SECONDS
                if fast_fail_rescue
                else self._FAST_FAIL_TOTAL_BUDGET_SECONDS
            )
            max_mirrors = (
                self._FAST_FAIL_RESCUE_MAX_MIRRORS
                if fast_fail_rescue
                else self._FAST_FAIL_MAX_MIRRORS
            )
            page_timeout_cap = (
                self._FAST_FAIL_RESCUE_PAGE_TIMEOUT_SECONDS
                if fast_fail_rescue
                else self._FAST_FAIL_PAGE_TIMEOUT_SECONDS
            )
            deadline = time.monotonic() + total_budget if fast_fail else None
            # Get working mirror (uses cache if available)
            preferred_mirror = self.mirror_manager.get_working_mirror()
            mirrors = [preferred_mirror]
            for mirror in self.mirror_manager.mirrors:
                if mirror not in mirrors:
                    mirrors.append(mirror)
            if fast_fail_rescue:
                hints = {
                    hint: idx for idx, hint in enumerate(self._FAST_FAIL_RESCUE_MIRROR_ORDER_HINTS)
                }

                def _mirror_rank(url: str) -> tuple[int, str]:
                    lowered = (url or "").lower()
                    for token, rank in hints.items():
                        if token in lowered:
                            return rank, lowered
                    return len(hints), lowered

                # Keep preferred mirror first, but reorder remaining mirrors by rescue effectiveness.
                tail = [m for m in mirrors if m != preferred_mirror]
                mirrors = [preferred_mirror, *sorted(tail, key=_mirror_rank)]
            if fast_fail and len(mirrors) > max_mirrors:
                mirrors = mirrors[:max_mirrors]

            blocked_count = 0
            for mirror in mirrors:
                page_timeout: float | None = None
                if deadline is not None:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        logger.info(f"[Sci-Hub] Fast-fail budget exhausted for {doi}")
                        break
                    page_timeout = max(1.0, min(page_timeout_cap, remaining))
                if mirror != preferred_mirror:
                    logger.info(f"[Sci-Hub] Switching mirror to {mirror} for {doi}")
                download_url, page_ok, blocked = self._get_download_url_from_mirror(
                    mirror,
                    doi,
                    fast_fail=fast_fail,
                    page_timeout=page_timeout,
                    allow_fast_fail_status_fallback=fast_fail_rescue,
                    allow_challenge_bypass=fast_fail_rescue,
                )
                if download_url:
                    logger.debug(f"[Sci-Hub] Found PDF URL: {download_url}")
                    return download_url
                if not page_ok:
                    self.mirror_manager.mark_failed(mirror)
                if blocked:
                    blocked_count += 1
                    self.mirror_manager.mark_failed(mirror)

            if cooldown_seconds > 0 and blocked_count and blocked_count == len(mirrors):
                self._blocked_until = time.monotonic() + cooldown_seconds
                logger.warning(
                    "[Sci-Hub] All mirrors returned block pages; cooling down for %ss",
                    int(cooldown_seconds),
                )

            logger.warning(f"[Sci-Hub] Could not extract download URL for {doi}")
            return None

        except Exception as e:
            logger.warning(f"[Sci-Hub] Error getting PDF URL for {doi}: {e}")
            # Invalidate mirror cache on exception
            self.mirror_manager.invalidate_cache()
            return None

    def _get_download_url_from_mirror(
        self,
        mirror: str,
        doi: str,
        *,
        fast_fail: bool = False,
        page_timeout: float | None = None,
        allow_fast_fail_status_fallback: bool = False,
        allow_challenge_bypass: bool = False,
    ) -> tuple[str | None, bool, bool]:
        """Attempt to extract a PDF URL from a specific Sci-Hub mirror."""
        formatted_doi = self.doi_processor.format_doi_for_url(doi) if doi.startswith("10.") else doi
        scihub_url = f"{mirror}/{formatted_doi}"
        logger.debug(f"[Sci-Hub] Accessing: {scihub_url}")

        html_content, status_code = self.downloader.get_page_content(
            scihub_url,
            timeout_seconds=page_timeout,
            force_challenge_bypass=allow_challenge_bypass,
        )
        if not html_content or status_code != 200:
            if doi.startswith("10.") and (not fast_fail or allow_fast_fail_status_fallback):
                fallback_url = f"{mirror}/{doi}"
                logger.debug(f"[Sci-Hub] Trying fallback: {fallback_url}")
                html_content, status_code = self.downloader.get_page_content(
                    fallback_url,
                    timeout_seconds=page_timeout,
                    force_challenge_bypass=allow_challenge_bypass,
                )
            if not html_content or status_code != 200:
                logger.warning(f"[Sci-Hub] Failed to access page: {status_code}")
                return None, False, False
        if html_content and self.parser._looks_like_scihub_block_page(html_content):
            logger.warning(f"[Sci-Hub] Detected blocked mirror page for {mirror}")
            return None, True, True

        download_url = self.parser.extract_download_url(html_content, mirror)
        if (
            not download_url
            and doi.startswith("10.")
            and (not fast_fail or allow_fast_fail_status_fallback)
        ):
            fallback_url = f"{mirror}/{doi}"
            logger.debug(f"[Sci-Hub] Extraction failed, trying fallback: {fallback_url}")
            html_content, status_code = self.downloader.get_page_content(
                fallback_url,
                timeout_seconds=page_timeout,
                force_challenge_bypass=allow_challenge_bypass,
            )
            if html_content and status_code == 200:
                download_url = self.parser.extract_download_url(html_content, mirror)

        if download_url:
            return download_url, True, False
        logger.warning(f"[Sci-Hub] Could not extract download URL for {doi} via {mirror}")
        return None, True, False

    @staticmethod
    def _should_skip_fast_fail_for_low_confidence_doi(doi: str) -> bool:
        """
        Skip Sci-Hub in fast-fail mode for malformed/low-confidence DOI patterns.

        These patterns are high-latency and showed near-zero recovery in practice.
        """
        lowered = (doi or "").strip().lower()
        if not lowered.startswith("10."):
            return False
        if "/" not in lowered:
            return True

        _prefix, suffix = lowered.split("/", 1)
        if not suffix or len(suffix) < 4:
            return True
        if ".pdf" in suffix:
            return True
        if "978-" in suffix:
            return True
        return "_" in suffix

    @classmethod
    def _is_fast_fail_rescue_doi(cls, doi: str) -> bool:
        lowered = (doi or "").strip().lower()
        if not lowered.startswith("10."):
            return False
        return any(lowered.startswith(prefix) for prefix in cls._FAST_FAIL_RESCUE_PREFIXES)
