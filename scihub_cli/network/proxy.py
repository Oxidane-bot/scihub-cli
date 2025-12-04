"""
Proxy rotation for IP obfuscation.
"""

from typing import Optional

from ..utils.logging import get_logger

logger = get_logger(__name__)


class ProxyRotator:
    """Handles proxy rotation for IP obfuscation"""

    def __init__(self, proxy_list: Optional[list[str]] = None):
        self.proxy_list = proxy_list or []
        self.current_proxy_index = 0
        self.failed_proxies: set[str] = set()

    def get_next_proxy(self) -> Optional[dict[str, str]]:
        """Get next working proxy"""
        if not self.proxy_list:
            return None

        available_proxies = [p for p in self.proxy_list if p not in self.failed_proxies]
        if not available_proxies:
            # Reset failed proxies if all failed
            logger.info("All proxies failed, resetting failed proxy list")
            self.failed_proxies.clear()
            available_proxies = self.proxy_list

        if not available_proxies:
            return None

        proxy = available_proxies[self.current_proxy_index % len(available_proxies)]
        self.current_proxy_index += 1

        return {"http": proxy, "https": proxy}

    def mark_proxy_failed(self, proxy: str):
        """Mark a proxy as failed"""
        self.failed_proxies.add(proxy)
        logger.warning(f"Marked proxy as failed: {proxy}")

    def get_proxy_count(self) -> int:
        """Get total number of proxies"""
        return len(self.proxy_list)

    def get_working_proxy_count(self) -> int:
        """Get number of working proxies"""
        return len(self.proxy_list) - len(self.failed_proxies)
