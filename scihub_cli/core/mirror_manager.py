"""
Mirror management and selection logic.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests

from ..config.mirrors import MirrorConfig
from ..config.settings import settings
from ..core.doi_processor import DOIProcessor
from ..core.parser import ContentParser
from ..utils.logging import get_logger

logger = get_logger(__name__)

# Shorter timeout for mirror testing (mirrors should respond quickly)
MIRROR_TEST_TIMEOUT = 5  # seconds
# A stable, old DOI is used only to validate that a user-supplied mirror can
# resolve an article and expose a PDF link.  It can be overridden for a
# particular environment with SCIHUB_MIRROR_PROBE_DOI.
MIRROR_HEALTHCHECK_DOI = "10.1038/323533a0"
MIRROR_HEALTHCHECK_MAX_PAGE_BYTES = 512 * 1024


class MirrorManager:
    """Manages mirror selection and testing."""

    def __init__(self, mirrors: list[str] | None = None, timeout: int = None):
        # Preserve an explicitly empty list.  It is useful for callers that
        # want to disable the Sci-Hub source without falling back to defaults.
        self.mirrors = list(mirrors) if mirrors is not None else MirrorConfig.get_all_mirrors()
        self.timeout = timeout or settings.timeout
        self.probe_doi = (
            os.getenv("SCIHUB_MIRROR_PROBE_DOI", MIRROR_HEALTHCHECK_DOI).strip()
            or MIRROR_HEALTHCHECK_DOI
        )
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            )
        }

        # Mirror caching
        self._cached_mirror: str | None = None
        self._cache_time: float | None = None
        self._cache_duration: int = 3600  # 1 hour TTL

        # Failed mirror blacklist (mirror_url -> failure_time)
        self._failed_mirrors: dict[str, float] = {}
        self._blacklist_duration: int = 300  # 5 minutes cooldown

    def get_working_mirror(self, force_refresh: bool = False) -> str:
        """
        Get a working mirror using tiered strategy with caching.

        Args:
            force_refresh: If True, bypass cache and test mirrors again

        Returns:
            Working mirror URL
        """
        # Check cache first
        if not force_refresh and self._is_cache_valid():
            logger.debug(f"Using cached mirror: {self._cached_mirror}")
            return self._cached_mirror

        # Cache miss or expired - find working mirror
        logger.info("Finding working mirror...")
        mirror = self._find_working_mirror()

        # Cache the result
        self._cached_mirror = mirror
        self._cache_time = time.time()
        logger.info(f"Cached mirror for {self._cache_duration}s: {mirror}")

        return mirror

    def _is_cache_valid(self) -> bool:
        """Check if cached mirror is still valid."""
        if self._cached_mirror is None or self._cache_time is None:
            return False

        elapsed = time.time() - self._cache_time
        return elapsed < self._cache_duration

    def invalidate_cache(self):
        """Invalidate cached mirror (call when mirror fails)."""
        if self._cached_mirror:
            logger.info(f"Invalidating cached mirror: {self._cached_mirror}")
            self.mark_failed(self._cached_mirror)

    def mark_failed(self, mirror: str) -> None:
        """Mark a mirror as failed and blacklist it temporarily."""
        self._failed_mirrors[mirror] = time.time()
        logger.info(f"Added {mirror} to blacklist for {self._blacklist_duration}s")
        if mirror == self._cached_mirror:
            self._cached_mirror = None
            self._cache_time = None

    def _is_blacklisted(self, mirror: str) -> bool:
        """Check if a mirror is currently blacklisted."""
        if mirror not in self._failed_mirrors:
            return False

        elapsed = time.time() - self._failed_mirrors[mirror]
        if elapsed >= self._blacklist_duration:
            # Blacklist expired, remove from list
            del self._failed_mirrors[mirror]
            logger.debug(f"Blacklist expired for {mirror}")
            return False

        logger.debug(
            f"Skipping blacklisted mirror {mirror} ({int(self._blacklist_duration - elapsed)}s remaining)"
        )
        return True

    def _find_working_mirror(self) -> str:
        """Find a working mirror using tiered parallel strategy."""
        # Tier 1: Easy mirrors first (test in parallel)
        logger.info("[Tier 1] Testing easy mirrors in parallel...")
        easy_mirrors = [
            m
            for m in self.mirrors
            if not self._is_blacklisted(m) and not MirrorConfig.is_hard_mirror(m)
        ]
        easy_blacklist_filtered_out = not easy_mirrors

        if easy_mirrors:
            result = self._test_mirrors_parallel(easy_mirrors, allow_403=False)
            if result:
                logger.info(f"SUCCESS: Using easy mirror: {result}")
                return result

        # Tier 2: Hard mirrors (test in parallel)
        logger.info("[Tier 2] Easy mirrors failed, testing hard mirrors in parallel...")
        hard_mirrors = [
            m
            for m in self.mirrors
            if not self._is_blacklisted(m) and MirrorConfig.is_hard_mirror(m)
        ]
        hard_blacklist_filtered_out = not hard_mirrors

        if hard_mirrors:
            result = self._test_mirrors_parallel(hard_mirrors, allow_403=True)
            if result:
                logger.info(f"SUCCESS: Using hard mirror: {result}")
                return result

        # All candidates were filtered out by blacklist: do a one-time forced retest.
        if easy_blacklist_filtered_out and hard_blacklist_filtered_out and self._failed_mirrors:
            logger.warning(
                "All mirrors are currently blacklisted; retrying once while ignoring blacklist"
            )
            easy_all = [m for m in self.mirrors if not MirrorConfig.is_hard_mirror(m)]
            hard_all = [m for m in self.mirrors if MirrorConfig.is_hard_mirror(m)]

            if easy_all:
                result = self._test_mirrors_parallel(easy_all, allow_403=False)
                if result:
                    logger.info(f"SUCCESS: Using easy mirror after blacklist fallback: {result}")
                    self._failed_mirrors.pop(result, None)
                    return result
            if hard_all:
                result = self._test_mirrors_parallel(hard_all, allow_403=True)
                if result:
                    logger.info(f"SUCCESS: Using hard mirror after blacklist fallback: {result}")
                    self._failed_mirrors.pop(result, None)
                    return result

        raise Exception("All mirrors are unavailable")

    def _test_mirrors_parallel(
        self, mirrors: list[str], allow_403: bool = False, max_workers: int = 5
    ) -> str | None:
        """
        Test multiple mirrors in parallel, return first working one.

        Args:
            mirrors: List of mirror URLs to test
            allow_403: Whether to accept 403 responses as "working"
            max_workers: Maximum parallel workers

        Returns:
            First working mirror URL, or None if all failed
        """
        if not mirrors:
            return None

        # Use fewer workers if we have fewer mirrors
        workers = min(max_workers, len(mirrors))

        executor = ThreadPoolExecutor(max_workers=workers)
        future_to_mirror = {
            executor.submit(self._test_mirror, mirror, allow_403): mirror for mirror in mirrors
        }

        try:
            # Return first successful result
            for future in as_completed(future_to_mirror):
                mirror = future_to_mirror[future]
                try:
                    is_working = future.result()
                    if is_working:
                        # Cancel remaining futures (best effort)
                        for f in future_to_mirror:
                            f.cancel()
                        return mirror
                except Exception as e:
                    logger.debug(f"Mirror test exception for {mirror}: {e}")
                    continue
        finally:
            # Don't block on slow/blocked mirrors once we have a result.
            executor.shutdown(wait=False, cancel_futures=True)

        return None

    def _test_mirror(self, mirror: str, allow_403: bool = False) -> bool:
        """Test a mirror against an article-specific page, not its home page.

        A successful home-page response is not useful evidence: dead mirrors
        commonly return a branded landing page with HTTP 200.  The health
        check therefore resolves a known DOI and requires either a PDF body or
        an extractable, PDF-shaped download link for that article.  ``allow_403``
        is retained for API compatibility, but a 403 is never considered
        healthy because it cannot verify article availability.
        """
        del allow_403  # A protected home/article page is not a verified mirror.
        article_url = self._build_healthcheck_url(mirror)
        try:
            response = requests.get(
                article_url,
                timeout=MIRROR_TEST_TIMEOUT,
                headers=self._headers,
                proxies={"http": None, "https": None},
            )
            if response.status_code != 200:
                logger.debug(f"FAIL: {mirror} article health check returned {response.status_code}")
                return False

            page = self._response_bytes(response)
            if not page or len(page) > MIRROR_HEALTHCHECK_MAX_PAGE_BYTES:
                logger.debug(f"FAIL: {mirror} article health page was empty or too large")
                return False
            if page[:4] == b"%PDF":
                logger.info(f"HEALTHY: {mirror} returned the probe article as a PDF")
                return True

            html = page.decode("utf-8", errors="replace")
            if ContentParser._looks_like_scihub_block_page(html):
                logger.warning(f"BLOCKED: {mirror} returned a block page for {self.probe_doi}")
                return False
            candidate = ContentParser().extract_download_url(html, mirror)
            if not candidate or not self._looks_like_pdf_candidate(candidate):
                logger.debug(f"FAIL: {mirror} exposed no PDF link for {self.probe_doi}")
                return False
            logger.info(f"HEALTHY: {mirror} exposed a PDF link for {self.probe_doi}")
            return True
        except requests.RequestException as e:
            logger.debug(f"FAIL: {mirror} failed: {e}")
            return False
        except (UnicodeError, ValueError, TypeError) as e:
            logger.debug(f"FAIL: {mirror} returned an invalid health-check response: {e}")
            return False

    def _build_healthcheck_url(self, mirror: str) -> str:
        """Build the article URL used by the mirror health check."""
        base = (mirror or "").strip().rstrip("/")
        return f"{base}/{DOIProcessor.format_doi_for_url(self.probe_doi)}"

    @staticmethod
    def _response_bytes(response: requests.Response) -> bytes:
        """Read a bounded-enough response body from requests or a test double."""
        content = getattr(response, "content", None)
        if isinstance(content, bytes):
            return content
        text = getattr(response, "text", "")
        return text.encode("utf-8") if isinstance(text, str) else b""

    @staticmethod
    def _looks_like_pdf_candidate(url: str) -> bool:
        """Return whether an extracted URL has a concrete PDF/download path."""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        path = (parsed.path or "").lower()
        query = (parsed.query or "").lower()
        return path.endswith(".pdf") or "/pdf/" in path or "/downloads/" in path or ".pdf" in query

    def test_all_mirrors(self) -> list[str]:
        """Test all mirrors and return working ones."""
        working_mirrors = []
        for mirror in self.mirrors:
            is_hard = MirrorConfig.is_hard_mirror(mirror)
            if self._test_mirror(mirror, allow_403=is_hard):
                working_mirrors.append(mirror)
        return working_mirrors
