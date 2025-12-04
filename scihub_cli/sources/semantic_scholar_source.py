"""
Semantic Scholar API integration for open access paper downloads.

Semantic Scholar indexes 200M+ papers with AI-driven search and provides
direct links to open access PDFs when available.
"""

import time
import requests
from typing import Optional, Tuple
from ..utils.logging import get_logger
from ..utils.retry import RetryConfig

logger = get_logger(__name__)

class SemanticScholarSource:
    """
    Semantic Scholar API client for finding and downloading open access papers.

    API Documentation: https://api.semanticscholar.org/
    """

    def __init__(self, api_key: Optional[str] = None, timeout: int = 30):
        """
        Initialize Semantic Scholar API client.

        Args:
            api_key: Semantic Scholar API key (optional, but recommended for better rate limits)
            timeout: Request timeout in seconds
        """
        self.name = "Semantic Scholar"
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = "https://api.semanticscholar.org/graph/v1"

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'scihub-cli/1.0 (academic research tool)'
        })

        if api_key:
            self.session.headers.update({
                'x-api-key': api_key
            })

        # Metadata cache to avoid duplicate API calls
        self._metadata_cache = {}

        # Retry configuration
        self.retry_config = RetryConfig(max_attempts=2, base_delay=2.0)

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
            logger.debug(f"[S2] Using cached metadata for {doi}")
            return self._metadata_cache[doi]

        logger.debug(f"[S2] Fetching metadata for {doi}")

        try:
            metadata = self._fetch_from_api(doi)
            if metadata:
                # Cache the result
                self._metadata_cache[doi] = metadata
                return metadata
            return None
        except Exception as e:
            logger.error(f"[S2] Failed to fetch metadata for {doi}: {e}")
            return None

    def _fetch_from_api(self, doi: str) -> Optional[dict]:
        """
        Fetch metadata from Semantic Scholar API with retry logic.

        Args:
            doi: DOI to search for

        Returns:
            Metadata dict or None
        """
        # Query by DOI
        paper_url = f"{self.base_url}/paper/DOI:{doi}"
        params = {
            'fields': 'title,year,isOpenAccess,openAccessPdf'
        }

        for attempt in range(self.retry_config.max_attempts):
            try:
                response = self.session.get(
                    paper_url,
                    params=params,
                    timeout=self.timeout
                )

                if response.status_code == 200:
                    data = response.json()

                    # Check if open access
                    is_oa = data.get('isOpenAccess', False)

                    if not is_oa:
                        logger.debug(f"[S2] Paper not open access: {doi}")
                        return None

                    # Get PDF URL
                    open_access_pdf = data.get('openAccessPdf')
                    pdf_url = None

                    if open_access_pdf:
                        pdf_url = open_access_pdf.get('url')

                    if not pdf_url:
                        logger.debug(f"[S2] No PDF URL available for {doi}")
                        return None

                    return {
                        'title': data.get('title', ''),
                        'year': str(data.get('year', '')),
                        'is_oa': True,
                        'pdf_url': pdf_url,
                        'source': 'Semantic Scholar'
                    }

                elif response.status_code == 429:
                    # Rate limit exceeded
                    retry_after = int(response.headers.get('Retry-After', 10))
                    logger.warning(f"[S2] Rate limit exceeded, waiting {retry_after}s")
                    if attempt < self.retry_config.max_attempts - 1:
                        time.sleep(retry_after)
                        continue
                    return None

                elif response.status_code == 404:
                    logger.debug(f"[S2] Paper not found: {doi}")
                    return None

                else:
                    logger.warning(f"[S2] API returned {response.status_code}")
                    return None

            except requests.Timeout:
                logger.warning(f"[S2] Request timeout (attempt {attempt + 1})")
                if attempt < self.retry_config.max_attempts - 1:
                    time.sleep(self.retry_config.base_delay * (attempt + 1))
                    continue
                return None

            except requests.RequestException as e:
                logger.error(f"[S2] Request error: {e}")
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
            logger.debug(f"[S2] No metadata found for {doi}")
            return None

        pdf_url = metadata.get('pdf_url')

        if pdf_url:
            logger.info(f"[S2] Found PDF for {doi}")
            logger.debug(f"[S2] PDF URL: {pdf_url}")
            return pdf_url
        else:
            logger.debug(f"[S2] No PDF URL available for {doi}")
            return None

    def get_pdf_url_with_metadata(self, doi: str) -> Tuple[Optional[str], Optional[dict]]:
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

        pdf_url = metadata.get('pdf_url')
        return pdf_url, metadata
