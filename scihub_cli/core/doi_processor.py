"""
DOI and URL normalization utilities.
"""

import re
from urllib.parse import quote, urlparse

from ..utils.logging import get_logger

logger = get_logger(__name__)


class DOIProcessor:
    """Handles DOI normalization and URL formatting."""

    DOI_PATTERN = r'\b10\.\d{4,}(?:\.\d+)*\/(?:(?!["&\'<>])\S)+\b'

    @classmethod
    def normalize_doi(cls, identifier: str) -> str:
        """Convert URL or DOI to a normalized DOI format."""
        # If it's already a DOI
        if re.match(cls.DOI_PATTERN, identifier):
            return identifier

        # If it's a URL, try to extract DOI
        parsed = urlparse(identifier)
        if parsed.netloc:
            path = parsed.path
            # Extract DOI from common URL patterns
            if "doi.org" in parsed.netloc:
                return path.strip("/")

            # Try to find DOI in the URL path
            doi_match = re.search(cls.DOI_PATTERN, identifier)
            if doi_match:
                return doi_match.group(0)

        # Return as is if we can't normalize
        return identifier

    @classmethod
    def format_doi_for_url(cls, doi: str) -> str:
        """Format DOI for use in Sci-Hub URL."""
        # Replace / with @ for Sci-Hub URL format
        formatted = doi.replace("/", "@")
        # Handle parentheses and other special characters
        formatted = quote(formatted, safe="@")
        return formatted
