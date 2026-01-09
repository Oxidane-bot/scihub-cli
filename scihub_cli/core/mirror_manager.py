"""
Mirror management and selection logic.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

from ..config.mirrors import MirrorConfig
from ..config.settings import settings
from ..utils.logging import get_logger

logger = get_logger(__name__)

# Shorter timeout for mirror testing (mirrors should respond quickly)
MIRROR_TEST_TIMEOUT = 5  # seconds


class MirrorManager:
    """Manages mirror selection and testing."""

    def __init__(self, mirrors: Optional[list[str]] = None, timeout: int = None):
        self.mirrors = mirrors or MirrorConfig.get_all_mirrors()
        self.timeout = timeout or settings.timeout
        self._headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/91.0.4472.124 Safari/537.36"
            )
        }

        # Mirror caching
        self._cached_mirror: Optional[str] = None
        self._cache_time: Optional[float] = None
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
            # Add to blacklist
            self._failed_mirrors[self._cached_mirror] = time.time()
            logger.info(f"Added {self._cached_mirror} to blacklist for {self._blacklist_duration}s")
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

        if hard_mirrors:
            result = self._test_mirrors_parallel(hard_mirrors, allow_403=True)
            if result:
                logger.info(f"SUCCESS: Using hard mirror: {result}")
                return result

        raise Exception("All mirrors are unavailable")

    def _test_mirrors_parallel(
        self, mirrors: list[str], allow_403: bool = False, max_workers: int = 5
    ) -> Optional[str]:
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
        """Test if a mirror is accessible (uses short timeout)."""
        try:
            response = requests.get(mirror, timeout=MIRROR_TEST_TIMEOUT, headers=self._headers)
            if response.status_code == 200:
                return True
            elif response.status_code == 403 and allow_403:
                logger.warning(
                    f"PROTECTED: {mirror} is 403 protected, but might work for downloads"
                )
                return True
            else:
                logger.debug(f"FAIL: {mirror} returned {response.status_code}")
                return False
        except requests.RequestException as e:
            logger.debug(f"FAIL: {mirror} failed: {e}")
            return False

    def test_all_mirrors(self) -> list[str]:
        """Test all mirrors and return working ones."""
        working_mirrors = []
        for mirror in self.mirrors:
            is_hard = MirrorConfig.is_hard_mirror(mirror)
            if self._test_mirror(mirror, allow_403=is_hard):
                working_mirrors.append(mirror)
        return working_mirrors
