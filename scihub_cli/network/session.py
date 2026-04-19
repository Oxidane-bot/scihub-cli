"""
HTTP session management.
"""

import threading
from urllib.parse import urlparse

import requests

from ..config.auto_tuning import load_auto_tuning
from ..utils.logging import get_logger

logger = get_logger(__name__)


class BasicSession:
    """Basic HTTP session without stealth features."""

    def __init__(self, timeout: int = 30):
        self._local = threading.local()
        self.timeout = timeout
        # Default browser User-Agent (will be overridden per-request based on domain)
        self.default_user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
        rules = load_auto_tuning()
        self._ua_overrides = (rules.get("ua_overrides") or {}) if isinstance(rules, dict) else {}

    def _get_session(self) -> requests.Session:
        session = getattr(self._local, "session", None)
        if session is None:
            session = requests.Session()
            # Avoid relying on environment proxies that can introduce flaky failures.
            session.trust_env = False
            self._local.session = session
        return session

    def _get_user_agent_for_url(self, url: str) -> str:
        """Get appropriate User-Agent based on domain."""
        domain = urlparse(url).netloc.lower()

        # MDPI uses User-Agent whitelist, allows curl but blocks browsers
        if "mdpi.com" in domain or "mdpi-res.com" in domain:
            return "curl/8.0.0"

        overrides = self._ua_overrides or {}
        curl_hosts = overrides.get("curl") or []
        if any(marker in domain for marker in curl_hosts):
            return "curl/8.0.0"

        browser_hosts = overrides.get("browser") or []
        if any(marker in domain for marker in browser_hosts):
            return self.default_user_agent

        # Default: use browser User-Agent for other sites
        return self.default_user_agent

    def get(self, url: str, **kwargs) -> requests.Response:
        """Simple GET request with domain-specific User-Agent."""
        kwargs.setdefault("timeout", self.timeout)

        # Set User-Agent based on target domain
        session = self._get_session()
        session.headers.update({"User-Agent": self._get_user_agent_for_url(url)})

        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        if "europepmc.org" in domain or "ebi.ac.uk" in domain:
            # Avoid flaky proxy paths for Europe PMC endpoints.
            kwargs.setdefault("proxies", {"http": None, "https": None})

        headers = kwargs.get("headers")
        if headers is None:
            headers = {}
            kwargs["headers"] = headers
        headers.setdefault("Referer", f"{parsed.scheme}://{parsed.netloc}/")

        return session.get(url, **kwargs)
