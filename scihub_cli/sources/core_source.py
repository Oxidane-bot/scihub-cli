"""
CORE API integration for open access paper downloads.

CORE aggregates over 32.8 million full-text open access articles from
thousands of repositories and journals worldwide.
"""

import time
from typing import Optional

import requests

from ..utils.logging import get_logger
from ..utils.retry import RetryConfig
from .base import PaperSource

logger = get_logger(__name__)


class CORESource(PaperSource):
    """
    CORE API client for finding and downloading open access papers.

    API Documentation: https://core.ac.uk/documentation/api
    """

    def __init__(self, api_key: Optional[str] = None, timeout: int = 30):
        """
        Initialize CORE API client.

        Args:
            api_key: CORE API key (optional, but recommended for better rate limits)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = "https://api.core.ac.uk/v3"

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "scihub-cli/1.0 (academic research tool)"})

        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})

        # Metadata cache to avoid duplicate API calls
        self._metadata_cache = {}

        # Retry configuration
        self.retry_config = RetryConfig(max_attempts=2, base_delay=2.0)

    @property
    def name(self) -> str:
        return "CORE"

    def can_handle(self, doi: str) -> bool:
        """CORE searches by DOI and only returns OA content."""
        return doi.startswith("10.")

    def get_metadata(self, doi: str) -> Optional[dict]:
        """
        Get metadata for a paper by DOI.

        Args:
            doi: DOI of the paper

        Returns:
            Metadata dict or None if not found
        """
        # Check cache first
        if doi in self._metadata_cache:
            logger.debug(f"[CORE] Using cached metadata for {doi}")
            return self._metadata_cache[doi]

        logger.debug(f"[CORE] Fetching metadata for {doi}")

        try:
            metadata = self._fetch_from_api(doi)
            if metadata:
                # Cache the result
                self._metadata_cache[doi] = metadata
                return metadata
            return None
        except Exception as e:
            logger.error(f"[CORE] Failed to fetch metadata for {doi}: {e}")
            return None

    def _fetch_from_api(self, doi: str) -> Optional[dict]:
        """
        Fetch metadata from CORE API with retry logic.

        Args:
            doi: DOI to search for

        Returns:
            Metadata dict or None
        """
        # Search by DOI
        search_url = f"{self.base_url}/search/works"
        params = {"q": f'doi:"{doi}"', "limit": 1}

        for attempt in range(self.retry_config.max_attempts):
            try:
                response = self.session.get(search_url, params=params, timeout=self.timeout)

                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])

                    if not results:
                        logger.debug(f"[CORE] No results found for {doi}")
                        return None

                    work = results[0]

                    # Check if full text is available
                    has_fulltext = work.get("fullText") or work.get("downloadUrl")

                    if not has_fulltext:
                        logger.debug(f"[CORE] No full text available for {doi}")
                        return None

                    return {
                        "title": work.get("title", ""),
                        "year": work.get("yearPublished"),
                        "is_oa": True,  # CORE only has OA content
                        "pdf_url": work.get("downloadUrl"),
                        "core_id": work.get("id"),
                        "source": "CORE",
                    }

                elif response.status_code == 429:
                    # Rate limit exceeded
                    retry_after = int(response.headers.get("Retry-After", 10))
                    logger.warning(f"[CORE] Rate limit exceeded, waiting {retry_after}s")
                    if attempt < self.retry_config.max_attempts - 1:
                        time.sleep(retry_after)
                        continue
                    return None

                elif response.status_code == 404:
                    logger.debug(f"[CORE] Paper not found: {doi}")
                    return None

                else:
                    logger.warning(f"[CORE] API returned {response.status_code}")
                    return None

            except requests.Timeout:
                logger.warning(f"[CORE] Request timeout (attempt {attempt + 1})")
                if attempt < self.retry_config.max_attempts - 1:
                    time.sleep(self.retry_config.base_delay * (attempt + 1))
                    continue
                return None

            except requests.RequestException as e:
                logger.error(f"[CORE] Request error: {e}")
                return None

        return None

    def get_pdf_url(self, doi: str) -> Optional[str]:
        """
        Get PDF download URL for a paper.

        Args:
            doi: DOI of the paper

        Returns:
            PDF URL or None if not available
        """
        metadata = self.get_metadata(doi)

        if not metadata:
            logger.debug(f"[CORE] No metadata found for {doi}")
            return None

        pdf_url = metadata.get("pdf_url")

        if pdf_url:
            logger.info(f"[CORE] Found PDF for {doi}")
            logger.debug(f"[CORE] PDF URL: {pdf_url}")
            return pdf_url
        else:
            logger.debug(f"[CORE] No PDF URL available for {doi}")
            return None

    def get_pdf_url_with_metadata(self, doi: str) -> tuple[Optional[str], Optional[dict]]:
        """
        Get both PDF URL and metadata in one call.

        Args:
            doi: DOI of the paper

        Returns:
            Tuple of (pdf_url, metadata)
        """
        metadata = self.get_metadata(doi)

        if not metadata:
            return None, None

        pdf_url = metadata.get("pdf_url")
        return pdf_url, metadata
