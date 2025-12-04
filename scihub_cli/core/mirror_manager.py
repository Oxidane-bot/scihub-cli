"""
Mirror management and selection logic.
"""

import time
from typing import Optional

import requests

from ..config.mirrors import MirrorConfig
from ..config.settings import settings
from ..utils.logging import get_logger

logger = get_logger(__name__)


class MirrorManager:
    """Manages mirror selection and testing."""

    def __init__(self, mirrors: Optional[list[str]] = None, timeout: int = None):
        self.mirrors = mirrors or MirrorConfig.get_all_mirrors()
        self.timeout = timeout or settings.timeout
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }
        )

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
        """Find a working mirror using tiered strategy."""
        # Tier 1: Easy mirrors first (fastest)
        logger.info("[Tier 1] Trying easy mirrors first...")
        easy_mirrors = MirrorConfig.get_easy_mirrors()
        for mirror in easy_mirrors:
            if self._is_blacklisted(mirror):
                continue
            if self._test_mirror(mirror):
                logger.info(f"SUCCESS: Using easy mirror: {mirror}")
                return mirror

        # Tier 2: Hard mirrors (sci-hub.se) as last resort
        logger.info("[Tier 2] Easy mirrors failed, trying hard mirrors...")
        hard_mirrors = MirrorConfig.get_hard_mirrors()
        for mirror in hard_mirrors:
            if self._is_blacklisted(mirror):
                continue
            if self._test_mirror(mirror, allow_403=True):
                logger.info(f"SUCCESS: Using hard mirror: {mirror}")
                return mirror

        raise Exception("All mirrors are unavailable")

    def _test_mirror(self, mirror: str, allow_403: bool = False) -> bool:
        """Test if a mirror is accessible."""
        try:
            response = self.session.get(mirror, timeout=self.timeout)
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
