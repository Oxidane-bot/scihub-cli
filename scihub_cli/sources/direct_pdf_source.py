"""
Direct PDF URL source implementation.

This source is used when the input identifier is already a direct link to a PDF.
It enables downloading from open-access repositories that expose stable PDF URLs
without requiring a DOI lookup.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse, urlunparse

from ..utils.logging import get_logger
from .base import PaperSource

logger = get_logger(__name__)


class DirectPDFSource(PaperSource):
    """Handle direct PDF links (e.g., institutional repositories, WordPress uploads)."""

    # Known high-signal direct-PDF patterns (from OA repository observations)
    DEFAULT_TRUSTED_PATTERNS = [
        # ERIC
        r"^https://files\.eric\.ed\.gov/fulltext/[A-Z]{2}\d+\.pdf$",
        # WordPress uploads
        r"^https?://[^/]+/wp-content/uploads/\d{4}/\d{2}/.+\.pdf$",
        # papers_submitted style
        r"^https?://[^/]+/papers_submitted/\d+/.+\.pdf$",
        # volume/issue style
        r"^https?://[^/]+/vol\d+/.+\.pdf$",
        # .edu repositories (very broad, but useful)
        r"^https?://[^/]+\.edu/.*\.pdf$",
    ]

    def __init__(self, trusted_patterns: list[str] | None = None):
        patterns = trusted_patterns or self.DEFAULT_TRUSTED_PATTERNS
        self._trusted_patterns = [re.compile(p) for p in patterns]

    @property
    def name(self) -> str:
        return "Direct PDF"

    def can_handle(self, identifier: str) -> bool:
        """
        Check whether the identifier looks like a direct PDF URL.

        This intentionally avoids network requests; final validation is done by the
        download layer (PDF header + minimum size checks).
        """
        cleaned = self._strip_fragment(identifier)
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False

        # High-signal allowlist patterns
        if any(p.match(cleaned) for p in self._trusted_patterns):
            return True

        # Generic direct-PDF heuristic
        if parsed.path.lower().endswith(".pdf"):
            return True

        # Some sites expose the filename in query string, e.g. ?file=paper.pdf
        return ".pdf" in (parsed.query or "").lower()

    def get_pdf_url(self, identifier: str) -> str | None:
        """Return the URL itself when it is a direct PDF link."""
        if not self.can_handle(identifier):
            return None
        url = self._strip_fragment(identifier)
        logger.debug(f"[Direct PDF] Using direct PDF URL: {url}")
        return url

    @staticmethod
    def _strip_fragment(url: str) -> str:
        parsed = urlparse(url)
        if not parsed.fragment:
            return url
        return urlunparse(parsed._replace(fragment=""))
