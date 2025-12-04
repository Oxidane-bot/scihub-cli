"""
HTML content parsing and URL extraction.
"""

import re
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from ..utils.logging import get_logger

logger = get_logger(__name__)


class ContentParser:
    """Handles HTML parsing and URL extraction."""

    def __init__(self):
        pass

    def extract_download_url(self, html_content: str, base_mirror: str) -> Optional[str]:
        """Extract the PDF download URL from Sci-Hub HTML."""
        soup = BeautifulSoup(html_content, "html.parser")

        # Look for the download button (onclick attribute)
        button_pattern = r"location\.href=['\"]([^'\"]+)['\"]"
        buttons = soup.find_all("button", onclick=re.compile(button_pattern))
        for button in buttons:
            onclick = button.get("onclick", "")
            match = re.search(button_pattern, onclick)
            if match:
                href = match.group(1)
                href = self._fix_url_format(href, base_mirror)
                logger.debug(f"Found download button (onclick): {href}")
                return self._clean_url(href)

        # Look for the download button or iframe
        iframe = soup.find("iframe", id="pdf")
        if iframe and iframe.get("src"):
            src = iframe.get("src")
            src = self._fix_url_format(src, base_mirror)
            logger.debug(f"Found download iframe: {src}")
            return self._clean_url(src)

        # Look for download button
        download_button = soup.find("a", string=re.compile(r"download", re.I))
        if download_button and download_button.get("href"):
            href = download_button.get("href")
            href = self._fix_url_format(href, base_mirror)
            logger.debug(f"Found download button: {href}")
            return self._clean_url(href)

        # Look for embed tags
        embed = soup.find("embed", attrs={"type": "application/pdf"})
        if embed and embed.get("src"):
            src = embed.get("src")
            src = self._fix_url_format(src, base_mirror)
            logger.debug(f"Found embedded PDF: {src}")
            return self._clean_url(src)

        # Search directly in the HTML content for download patterns
        patterns = [
            r"location\.href=['\"]([^'\"]+)['\"]",
            r'href=["\'](/downloads/[^"\']+)["\']',
            r'src=["\'](/downloads/[^"\']+\.pdf)["\']',
            r'/downloads/[^"\'<>\s]+\.pdf',
        ]

        for pattern in patterns:
            matches = re.findall(pattern, html_content)
            if matches:
                download_link = matches[0]
                if isinstance(download_link, tuple):
                    download_link = download_link[0]
                download_link = (
                    download_link.split("#")[0] if "#" in download_link else download_link
                )
                full_url = self._fix_url_format(download_link, base_mirror)
                logger.debug(f"Found download link with pattern {pattern}: {full_url}")
                return self._clean_url(full_url)

        logger.warning("Could not find download URL in HTML")
        return None

    def _fix_url_format(self, url: str, mirror: str) -> str:
        """Fix common URL formatting issues."""
        # Handle relative URLs (starting with /)
        if url.startswith("/"):
            parsed_mirror = urlparse(mirror)
            base_url = f"{parsed_mirror.scheme}://{parsed_mirror.netloc}"
            return urljoin(base_url, url)

        # Handle relative URLs without leading slash
        if not url.startswith("http") and "://" not in url:
            return urljoin(mirror, url)

        # Handle incorrectly formatted domain (sci-hub.sedownloads)
        parsed = urlparse(url)
        if "downloads" in parsed.netloc:
            domain = parsed.netloc.split("downloads")[0]
            path = f"/downloads{parsed.netloc.split('downloads')[1]}{parsed.path}"
            query = f"?{parsed.query}" if parsed.query else ""
            return f"https://{domain}{path}{query}"

        return url

    def _clean_url(self, url: str) -> str:
        """Clean the URL by removing fragments and adding download parameter."""
        # Remove the fragment (anything after #)
        if "#" in url:
            url = url.split("#")[0]

        # Add the download parameter if not already present
        if "download=true" not in url:
            url += ("&" if "?" in url else "?") + "download=true"

        return url
