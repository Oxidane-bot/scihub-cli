"""
Generic HTML landing page source implementation.

This source tries to extract a direct PDF link from an article landing page.
It is primarily intended for open-access repository/journal pages where the PDF
URL is discoverable in the HTML (e.g. citation meta tags or download links).
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse

from ..core.downloader import FileDownloader
from ..core.pdf_link_extractor import extract_pdf_candidates
from ..utils.logging import get_logger
from .base import PaperSource

logger = get_logger(__name__)


class HTMLLandingSource(PaperSource):
    """Extract PDF URLs from generic HTML pages."""

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
        return not parsed.path.lower().endswith(".pdf")

    def get_pdf_url(self, identifier: str) -> str | None:
        if not self.can_handle(identifier):
            return None

        base_url = self._strip_fragment(identifier)
        html, status = self.downloader.get_page_content(base_url)
        if not html or status != 200:
            return None

        # Sometimes a server returns a PDF even for a non-.pdf URL.
        if html.lstrip().startswith("%PDF"):
            logger.debug("[HTML Landing] Page content appears to be a PDF; using original URL")
            return base_url

        candidates = extract_pdf_candidates(html, base_url, min_score=1)
        best = candidates[0] if candidates else None
        if best:
            logger.info(f"[HTML Landing] Extracted PDF URL: {best}")
        return best

    @staticmethod
    def _strip_fragment(url: str) -> str:
        parsed = urlparse(url)
        if not parsed.fragment:
            return url
        return urlunparse(parsed._replace(fragment=""))
