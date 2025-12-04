"""
Unpaywall source implementation.
"""

from typing import Any, Optional

import requests

from ..utils.logging import get_logger
from ..utils.retry import (
    APIRetryConfig,
    PermanentError,
    RetryableError,
    retry_with_classification,
)
from .base import PaperSource

logger = get_logger(__name__)


class UnpaywallSource(PaperSource):
    """Unpaywall open access paper source."""

    def __init__(self, email: str, timeout: int = 30):
        """
        Initialize Unpaywall source.

        Args:
            email: Email address required by Unpaywall API
            timeout: Request timeout in seconds
        """
        self.email = email
        self.timeout = timeout
        self.base_url = "https://api.unpaywall.org/v2"
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": f"scihub-cli/1.0 (mailto:{email})"})

        # Metadata caching
        self._metadata_cache: dict[str, Optional[dict]] = {}

        # Retry configuration for API calls
        self.retry_config = APIRetryConfig()

    @property
    def name(self) -> str:
        return "Unpaywall"

    def can_handle(self, doi: str) -> bool:
        """Unpaywall can query any DOI, but only returns OA articles."""
        return doi.startswith("10.")

    def get_pdf_url(self, doi: str) -> Optional[str]:
        """
        Get PDF download URL from Unpaywall using cached metadata.

        Args:
            doi: The DOI to look up

        Returns:
            PDF URL if open access is available, None otherwise
        """
        metadata = self._fetch_metadata(doi)
        if not metadata:
            return None

        # Check if paper is open access
        if not metadata.get("is_oa"):
            logger.debug(f"[Unpaywall] Paper {doi} is not open access")
            return None

        # Get PDF URL from cached metadata
        pdf_url = metadata.get("pdf_url")
        if pdf_url:
            oa_status = metadata.get("oa_status", "unknown")
            logger.info(f"[Unpaywall] Found OA paper (status: {oa_status}): {doi}")
            logger.debug(f"[Unpaywall] PDF URL: {pdf_url}")
            return pdf_url
        else:
            logger.warning(f"[Unpaywall] No PDF URL in OA location for {doi}")
            return None

    def get_metadata(self, doi: str) -> Optional[dict[str, Any]]:
        """
        Get metadata from Unpaywall (returns cached if available).

        Args:
            doi: The DOI to look up

        Returns:
            Dictionary with title (str), year (int), journal (str),
            is_oa (bool), oa_status (str), or None if not found
        """
        return self._fetch_metadata(doi)

    def _fetch_metadata(self, doi: str) -> Optional[dict[str, str]]:
        """
        Fetch and cache metadata from Unpaywall API.

        Args:
            doi: The DOI to look up

        Returns:
            Dictionary with metadata or None
        """
        # Check cache first
        if doi in self._metadata_cache:
            logger.debug(f"[Unpaywall] Using cached metadata for {doi}")
            return self._metadata_cache[doi]

        # Cache miss - fetch from API with retry
        logger.debug(f"[Unpaywall] Fetching metadata for {doi}")

        def _attempt_fetch():
            return self._fetch_from_api(doi)

        try:
            metadata = retry_with_classification(
                _attempt_fetch, self.retry_config, f"Unpaywall API for {doi}"
            )
            # Cache result (even if None)
            self._metadata_cache[doi] = metadata
            return metadata
        except PermanentError:
            # Cache permanent failures too
            self._metadata_cache[doi] = None
            return None
        except Exception:
            # Don't cache transient failures that exhausted retries
            return None

    def _fetch_from_api(self, doi: str) -> Optional[dict[str, str]]:
        """
        Single API fetch attempt with error classification.

        Args:
            doi: The DOI to look up

        Returns:
            Dictionary with metadata

        Raises:
            PermanentError: For 404 or not open access
            RetryableError: For timeouts, rate limits, server errors
        """
        try:
            url = f"{self.base_url}/{doi}"
            params = {"email": self.email}

            response = self.session.get(url, params=params, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json()

                # Parse metadata
                best_oa = data.get("best_oa_location", {})

                # Prefer url_for_pdf (direct PDF link)
                pdf_url = best_oa.get("url_for_pdf")

                # If no direct PDF, validate the fallback URL
                if not pdf_url:
                    fallback_url = best_oa.get("url")
                    if fallback_url and self._looks_like_pdf_url(fallback_url):
                        logger.debug(f"[Unpaywall] Using validated fallback URL: {fallback_url}")
                        pdf_url = fallback_url
                    else:
                        logger.debug(
                            f"[Unpaywall] Only landing page available, no direct PDF: {fallback_url}"
                        )
                        # pdf_url remains None

                # Keep year as int for proper comparison with thresholds
                year = data.get("year")
                return {
                    "title": data.get("title", ""),
                    "year": int(year) if year else None,
                    "journal": data.get("journal_name", ""),
                    "is_oa": data.get("is_oa", False),
                    "oa_status": data.get("oa_status", ""),
                    "pdf_url": pdf_url,
                }

            elif response.status_code == 404:
                logger.debug(f"[Unpaywall] DOI not found: {doi}")
                raise PermanentError("DOI not found")

            elif response.status_code == 429:
                logger.warning(f"[Unpaywall] Rate limited for {doi}")
                raise RetryableError("Rate limited")

            elif response.status_code >= 500:
                logger.warning(f"[Unpaywall] Server error {response.status_code} for {doi}")
                raise RetryableError(f"Server error {response.status_code}")

            else:
                logger.warning(f"[Unpaywall] API returned {response.status_code} for {doi}")
                raise PermanentError(f"Unexpected status {response.status_code}")

        except requests.Timeout as e:
            logger.warning(f"[Unpaywall] Request timeout for {doi}")
            raise RetryableError("Request timeout") from e

        except requests.RequestException as e:
            logger.warning(f"[Unpaywall] Request error for {doi}: {e}")
            raise RetryableError(f"Request error: {e}") from e

        except (KeyError, ValueError) as e:
            logger.warning(f"[Unpaywall] Error parsing response for {doi}: {e}")
            raise PermanentError(f"Parse error: {e}") from e

    def _looks_like_pdf_url(self, url: str) -> bool:
        """
        Check if URL likely points to a PDF file.

        Args:
            url: URL to validate

        Returns:
            True if URL appears to be a direct PDF, False otherwise
        """
        if not url:
            return False

        url_lower = url.lower()

        # Direct PDF file URLs
        if url_lower.endswith(".pdf"):
            return True

        # Reject known landing page patterns
        landing_patterns = [
            "/doi.org/",  # DOI redirects
            "/abstract",  # Abstract pages
            "/article/",  # Article landing pages
            "/stable/",  # JSTOR landing
            "ecuworks",  # ECU institutional repo
            "/pure/",  # Research portals
            "researchgate",  # ResearchGate profiles
        ]

        for pattern in landing_patterns:
            if pattern in url_lower:
                logger.debug(f"[Unpaywall] Detected landing page pattern '{pattern}' in {url}")
                return False

        # Accept known PDF serving patterns
        pdf_patterns = [
            "/pdf",
            "download",
            "content/pdf",
            "/article-pdf/",
            "/pdfviewer/",
            "viewer/pdf",
        ]

        return any(pattern in url_lower for pattern in pdf_patterns)
