"""
HTTP session management with stealth features.
"""

import random
import time
from urllib.parse import urlparse

import requests

from ..utils.logging import get_logger

logger = get_logger(__name__)


class StealthConfig:
    """Configuration for stealth downloading"""

    # Realistic User-Agent rotation pool
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/121.0.0.0",
    ]

    # Realistic browser headers
    COMMON_HEADERS = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "sec-ch-ua": '"Not A(Brand";v="99", "Google Chrome";v="121", "Chromium";v="121"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
    }

    # Rate limiting settings
    MIN_DELAY = 2.0
    MAX_DELAY = 8.0
    BURST_DELAY = 15.0
    MAX_REQUESTS_PER_MINUTE = 8
    MAX_REQUESTS_PER_SESSION = 25
    SESSION_COOLDOWN = 30


class StealthSession:
    """Enhanced session with anti-detection features"""

    def __init__(self):
        self.session = requests.Session()
        self.request_count = 0
        self.last_request_time = 0
        self.requests_this_minute = []
        self.current_ua_index = random.randint(0, len(StealthConfig.USER_AGENTS) - 1)
        self._setup_session()

    def _setup_session(self):
        """Configure session with realistic headers"""
        headers = StealthConfig.COMMON_HEADERS.copy()
        headers["User-Agent"] = StealthConfig.USER_AGENTS[self.current_ua_index]
        self.session.headers.update(headers)

        # Configure session settings
        self.session.max_redirects = 5

        # Add some entropy to TLS fingerprinting
        adapter = requests.adapters.HTTPAdapter(pool_connections=10, pool_maxsize=20, max_retries=3)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _should_rotate_session(self) -> bool:
        """Check if session should be rotated"""
        return self.request_count >= StealthConfig.MAX_REQUESTS_PER_SESSION

    def _wait_for_rate_limit(self, mirror_url: str):
        """Implement intelligent rate limiting"""
        current_time = time.time()

        # Clean old requests from the tracking list
        self.requests_this_minute = [
            req_time for req_time in self.requests_this_minute if current_time - req_time < 60
        ]

        # Check if we're hitting rate limits
        if len(self.requests_this_minute) >= StealthConfig.MAX_REQUESTS_PER_MINUTE:
            logger.info(f"Rate limit reached for {mirror_url}, waiting...")
            time.sleep(StealthConfig.BURST_DELAY)
            self.requests_this_minute = []

        # Calculate delay since last request
        time_since_last = current_time - self.last_request_time
        min_delay = random.uniform(StealthConfig.MIN_DELAY, StealthConfig.MAX_DELAY)

        if time_since_last < min_delay:
            wait_time = min_delay - time_since_last
            time.sleep(wait_time)

        self.last_request_time = time.time()
        self.requests_this_minute.append(self.last_request_time)

    def get(self, url: str, **kwargs) -> requests.Response:
        """Enhanced GET request with stealth features"""
        # Extract mirror URL for rate limiting
        mirror_url = f"{urlparse(url).scheme}://{urlparse(url).netloc}"

        # Apply rate limiting
        self._wait_for_rate_limit(mirror_url)

        # Rotate session if needed
        if self._should_rotate_session():
            logger.info("Rotating session for better stealth...")
            time.sleep(StealthConfig.SESSION_COOLDOWN)
            self._rotate_session()

        # Add some request-specific headers
        headers = kwargs.get("headers", {})
        headers["Referer"] = f"{mirror_url}/"
        kwargs["headers"] = headers

        # Make the request
        response = self.session.get(url, **kwargs)
        self.request_count += 1

        return response

    def _rotate_session(self):
        """Rotate session with new fingerprint"""
        self.session.close()
        self.session = requests.Session()
        self.request_count = 0
        self.current_ua_index = (self.current_ua_index + 1) % len(StealthConfig.USER_AGENTS)
        self._setup_session()


class BasicSession:
    """Basic HTTP session without stealth features."""

    def __init__(self, timeout: int = 30):
        self.session = requests.Session()
        self.timeout = timeout
        # Default browser User-Agent (will be overridden per-request based on domain)
        self.default_user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"

    def _get_user_agent_for_url(self, url: str) -> str:
        """Get appropriate User-Agent based on domain."""
        domain = urlparse(url).netloc.lower()

        # MDPI uses User-Agent whitelist, allows curl but blocks browsers
        if "mdpi.com" in domain or "mdpi-res.com" in domain:
            return "curl/8.0.0"

        # Default: use browser User-Agent for other sites
        return self.default_user_agent

    def get(self, url: str, **kwargs) -> requests.Response:
        """Simple GET request with domain-specific User-Agent."""
        kwargs.setdefault("timeout", self.timeout)

        # Set User-Agent based on target domain
        self.session.headers.update({"User-Agent": self._get_user_agent_for_url(url)})

        return self.session.get(url, **kwargs)
