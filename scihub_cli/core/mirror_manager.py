"""
Mirror management and selection logic.
"""

import requests
from typing import List, Optional
from ..config.mirrors import MirrorConfig, MirrorTier
from ..config.settings import settings
from ..utils.logging import get_logger

logger = get_logger(__name__)

class MirrorManager:
    """Manages mirror selection and testing."""
    
    def __init__(self, 
                 mirrors: Optional[List[str]] = None,
                 timeout: int = None):
        self.mirrors = mirrors or MirrorConfig.get_all_mirrors()
        self.timeout = timeout or settings.timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
    
    def get_working_mirror(self) -> str:
        """Get a working mirror using tiered strategy: easy first, then hard."""
        
        # Tier 1: Easy mirrors first (fastest)
        logger.info("[Tier 1] Trying easy mirrors first...")
        easy_mirrors = MirrorConfig.get_easy_mirrors()
        for mirror in easy_mirrors:
            if self._test_mirror(mirror):
                logger.info(f"SUCCESS: Using easy mirror: {mirror}")
                return mirror
        
        # Tier 2: Hard mirrors (sci-hub.se) as last resort
        logger.info("[Tier 2] Easy mirrors failed, trying hard mirrors...")
        hard_mirrors = MirrorConfig.get_hard_mirrors()
        for mirror in hard_mirrors:
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
                logger.warning(f"PROTECTED: {mirror} is 403 protected, but might work for downloads")
                return True
            else:
                logger.debug(f"FAIL: {mirror} returned {response.status_code}")
                return False
        except requests.RequestException as e:
            logger.debug(f"FAIL: {mirror} failed: {e}")
            return False
    
    def test_all_mirrors(self) -> List[str]:
        """Test all mirrors and return working ones."""
        working_mirrors = []
        for mirror in self.mirrors:
            is_hard = MirrorConfig.is_hard_mirror(mirror)
            if self._test_mirror(mirror, allow_403=is_hard):
                working_mirrors.append(mirror)
        return working_mirrors