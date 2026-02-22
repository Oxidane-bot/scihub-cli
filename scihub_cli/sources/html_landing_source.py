"""
Generic HTML landing page source implementation.

This source tries to extract a direct PDF link from an article landing page.
It is primarily intended for open-access repository/journal pages where the PDF
URL is discoverable in the HTML (e.g. citation meta tags or download links).
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from ..core.downloader import FileDownloader
from ..core.pdf_link_extractor import derive_publisher_pdf_candidates, extract_ranked_pdf_candidates
from ..utils.logging import get_logger
from .base import PaperSource

logger = get_logger(__name__)


class HTMLLandingSource(PaperSource):
    """Extract PDF URLs from generic HTML pages."""

    _MIN_CANDIDATE_SCORE = 500
    _MAX_PROBE_CANDIDATES = 3
    _FAST_FAIL_SKIP_HTML_HOST_MARKERS = (
        "sciencedirect.com",
        "researchgate.net",
    )
    _FAST_FAIL_FORCE_PAGE_BYPASS_HOST_MARKERS = ("mdpi.com",)
    _FAST_FAIL_ACADEMIC_HINTS = (
        "journal",
        "research",
        "scholar",
        "library",
        "archive",
        "repository",
        "university",
        "institute",
    )
    _ACADEMIC_HOST_MARKERS = (
        "arxiv.org",
        "ncbi.nlm.nih.gov",
        "pmc.ncbi.nlm.nih.gov",
        "sciencedirect.com",
        "springer.com",
        "nature.com",
        "wiley.com",
        "onlinelibrary.wiley.com",
        "tandfonline.com",
        "sagepub.com",
        "mdpi.com",
        "ieeexplore.ieee.org",
        "acm.org",
        "jstor.org",
        "scielo.org",
        "researchgate.net",
        "semanticscholar.org",
        "doaj.org",
        "hindawi.com",
        "frontiersin.org",
    )
    _NON_ACADEMIC_HOST_MARKERS = (
        "tiktok.com",
        "instagram.com",
        "facebook.com",
        "x.com",
        "twitter.com",
        "youtube.com",
        "youtu.be",
        "reddit.com",
        "bbc.com",
        "cnn.com",
        "abcnews.com",
        "consumerreports.org",
        "creativebloq.com",
        "medium.com",
        "luxuryestate.com",
        "campaignlive.com",
        "campaignasia.com",
        "healthline.com",
        "hbr.org",
        "carscoops.com",
        "thisismoney.co.uk",
        "topgear.com",
        "tesla.com",
        "jaguar.com",
        "wikipedia.org",
    )

    def __init__(self, downloader: FileDownloader):
        self.downloader = downloader

    @property
    def name(self) -> str:
        return "HTML Landing"

    def can_handle(self, identifier: str) -> bool:
        cleaned = self._strip_fragment(identifier)
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False

        # If the URL already looks like a direct PDF, let DirectPDFSource handle it first.
        if parsed.path.lower().endswith(".pdf"):
            return False

        host = parsed.netloc.lower()
        fast_fail = bool(getattr(self.downloader, "fast_fail", False))
        if fast_fail and not self._is_likely_academic_host(host):
            logger.debug(f"[HTML Landing] Fast-fail skip for non-academic host: {host}")
            return False

        if self._is_obvious_non_academic_host(host):
            logger.debug(f"[HTML Landing] Skipping obvious non-academic host: {host}")
            return False

        return True

    def get_pdf_url(self, identifier: str) -> str | None:
        if not self.can_handle(identifier):
            return None

        base_url = self._strip_fragment(identifier)
        host = urlparse(base_url).netloc.lower()
        fast_fail = bool(getattr(self.downloader, "fast_fail", False))
        if fast_fail and self._should_skip_html_fetch(host):
            logger.debug(
                f"[HTML Landing] Fast-fail skip challenge-heavy host before prefetch: {host}"
            )
            return None

        # Try deterministic publisher URL derivation before full-page fetch.
        prefetch_candidates = derive_publisher_pdf_candidates(base_url)
        prefetched = self._probe_candidates(prefetch_candidates, mode="prefetch")
        if prefetched:
            return prefetched

        force_challenge_bypass = fast_fail and any(
            marker in host for marker in self._FAST_FAIL_FORCE_PAGE_BYPASS_HOST_MARKERS
        )
        html, status = self._fetch_page_content(
            base_url, force_challenge_bypass=force_challenge_bypass
        )
        if not html or status != 200:
            return None

        # Sometimes a server returns a PDF even for a non-.pdf URL.
        if html.lstrip().startswith("%PDF"):
            logger.debug("[HTML Landing] Page content appears to be a PDF; using original URL")
            return base_url

        ranked_candidates = extract_ranked_pdf_candidates(html, base_url)
        candidates = [url for score, url in ranked_candidates if score >= self._MIN_CANDIDATE_SCORE]
        if not candidates:
            logger.debug(
                "[HTML Landing] No high-confidence PDF candidates found "
                f"(threshold={self._MIN_CANDIDATE_SCORE})"
            )
            return None

        # Optional probe to avoid selecting tracker/challenge endpoints when multiple
        # candidates are present.
        probed = self._probe_candidates(candidates, mode="html")
        if probed:
            return probed

        # In fast-fail mode, do not trust unprobed candidates. This avoids expensive
        # dead-end downloads (e.g., login/challenge endpoints masquerading as PDFs).
        if fast_fail:
            logger.debug("[HTML Landing] Fast-fail: rejecting unprobed PDF candidate(s)")
            return None

        best = candidates[0]
        logger.info(f"[HTML Landing] Extracted PDF URL: {best}")
        return best

    @staticmethod
    def _strip_fragment(url: str) -> str:
        parsed = urlparse(url)
        if not parsed.fragment:
            return url
        return urlunparse(parsed._replace(fragment=""))

    @classmethod
    def _is_obvious_non_academic_host(cls, host: str) -> bool:
        if not host:
            return False

        if host.endswith(".edu") or host.endswith(".gov") or ".ac." in host:
            return False

        if any(marker in host for marker in cls._ACADEMIC_HOST_MARKERS):
            return False

        return any(marker in host for marker in cls._NON_ACADEMIC_HOST_MARKERS)

    @classmethod
    def _is_likely_academic_host(cls, host: str) -> bool:
        if not host:
            return False
        if host.endswith(".edu") or host.endswith(".gov") or ".ac." in host:
            return True
        if any(marker in host for marker in cls._ACADEMIC_HOST_MARKERS):
            return True
        return any(hint in host for hint in cls._FAST_FAIL_ACADEMIC_HINTS)

    def _probe_candidates(self, candidates: list[str], *, mode: str) -> str | None:
        if not candidates:
            return None
        probe_pdf_url = getattr(self.downloader, "probe_pdf_url", None)
        if not callable(probe_pdf_url):
            return candidates[0]
        for candidate in candidates[: self._MAX_PROBE_CANDIDATES]:
            try:
                if probe_pdf_url(candidate):
                    logger.info(f"[HTML Landing] Extracted PDF URL ({mode} probed): {candidate}")
                    return candidate
            except Exception as e:
                logger.debug(f"[HTML Landing] Probe failed for {candidate}: {e}")
        return None

    def _fetch_page_content(
        self, url: str, *, force_challenge_bypass: bool
    ) -> tuple[str | None, int | None]:
        fetcher = self.downloader.get_page_content
        if force_challenge_bypass:
            try:
                return fetcher(url, force_challenge_bypass=True)
            except TypeError:
                logger.debug(
                    "[HTML Landing] Downloader does not support force_challenge_bypass kwarg"
                )
        return fetcher(url)

    @classmethod
    def _should_skip_html_fetch(cls, host: str) -> bool:
        return any(marker in host for marker in cls._FAST_FAIL_SKIP_HTML_HOST_MARKERS)
