"""
OpenAlex API integration for open access paper downloads.

OpenAlex provides access to 250M+ works with frequently updated data
and comprehensive open access information.
"""

import time
import requests
from typing import Optional, Tuple
from ..utils.logging import get_logger
from ..utils.retry import RetryConfig

logger = get_logger(__name__)

class OpenAlexSource:
    """
    OpenAlex API client for finding and downloading open access papers.

    API Documentation: https://docs.openalex.org/
    """

    def __init__(self, email: Optional[str] = None, timeout: int = 30):
        """
        Initialize OpenAlex API client.

        Args:
            email: Contact email for polite pool (optional but recommended)
            timeout: Request timeout in seconds
        """
        self.name = "OpenAlex"
        self.email = email
        self.timeout = timeout
        self.base_url = "https://api.openalex.org"

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': f'scihub-cli/1.0 (mailto:{email})' if email else 'scihub-cli/1.0'
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
            logger.debug(f"[OpenAlex] Using cached metadata for {doi}")
            return self._metadata_cache[doi]

        logger.debug(f"[OpenAlex] Fetching metadata for {doi}")

        try:
            metadata = self._fetch_from_api(doi)
            if metadata:
                # Cache the result
                self._metadata_cache[doi] = metadata
                return metadata
            return None
        except Exception as e:
            logger.error(f"[OpenAlex] Failed to fetch metadata for {doi}: {e}")
            return None

    def _fetch_from_api(self, doi: str) -> Optional[dict]:
        """
        Fetch metadata from OpenAlex API with retry logic.

        Args:
            doi: DOI to search for

        Returns:
            Metadata dict or None
        """
        # Query by DOI
        work_url = f"{self.base_url}/works/doi:{doi}"

        for attempt in range(self.retry_config.max_attempts):
            try:
                response = self.session.get(
                    work_url,
                    timeout=self.timeout
                )

                if response.status_code == 200:
                    data = response.json()

                    # Check if open access
                    open_access = data.get('open_access', {})
                    is_oa = open_access.get('is_oa', False)

                    if not is_oa:
                        logger.debug(f"[OpenAlex] Paper not open access: {doi}")
                        return None

                    # Try to find PDF URL from multiple locations
                    pdf_url = self._extract_pdf_url(data)

                    if not pdf_url:
                        logger.debug(f"[OpenAlex] No PDF URL available for {doi}")
                        return None

                    return {
                        'title': data.get('title', ''),
                        'year': str(data.get('publication_year', '')),
                        'is_oa': True,
                        'oa_status': open_access.get('oa_status', ''),
                        'pdf_url': pdf_url,
                        'openalex_id': data.get('id'),
                        'source': 'OpenAlex'
                    }

                elif response.status_code == 429:
                    # Rate limit exceeded
                    retry_after = int(response.headers.get('Retry-After', 10))
                    logger.warning(f"[OpenAlex] Rate limit exceeded, waiting {retry_after}s")
                    if attempt < self.retry_config.max_attempts - 1:
                        time.sleep(retry_after)
                        continue
                    return None

                elif response.status_code == 404:
                    logger.debug(f"[OpenAlex] Paper not found: {doi}")
                    return None

                else:
                    logger.warning(f"[OpenAlex] API returned {response.status_code}")
                    return None

            except requests.Timeout:
                logger.warning(f"[OpenAlex] Request timeout (attempt {attempt + 1})")
                if attempt < self.retry_config.max_attempts - 1:
                    time.sleep(self.retry_config.base_delay * (attempt + 1))
                    continue
                return None

            except requests.RequestException as e:
                logger.error(f"[OpenAlex] Request error: {e}")
                return None

        return None

    def _extract_pdf_url(self, data: dict) -> Optional[str]:
        """
        Extract PDF URL from work data.

        Tries multiple strategies:
        1. Check open_access.oa_url
        2. Check primary_location.pdf_url
        3. Check all locations for pdf_url

        Args:
            data: Work data from OpenAlex API

        Returns:
            PDF URL or None
        """
        # Strategy 1: Use oa_url if available
        open_access = data.get('open_access', {})
        oa_url = open_access.get('oa_url')
        if oa_url and self._looks_like_pdf_url(oa_url):
            logger.debug(f"[OpenAlex] Using oa_url: {oa_url}")
            return oa_url

        # Strategy 2: Check primary location
        primary_location = data.get('primary_location', {})
        if primary_location:
            pdf_url = primary_location.get('pdf_url')
            if pdf_url:
                logger.debug(f"[OpenAlex] Using primary_location pdf_url: {pdf_url}")
                return pdf_url

        # Strategy 3: Check all locations
        locations = data.get('locations', [])
        for location in locations:
            if location.get('is_oa'):
                pdf_url = location.get('pdf_url')
                if pdf_url:
                    logger.debug(f"[OpenAlex] Using location pdf_url: {pdf_url}")
                    return pdf_url

        return None

    def _looks_like_pdf_url(self, url: str) -> bool:
        """
        Check if URL likely points to a PDF file.

        Args:
            url: URL to validate

        Returns:
            True if URL appears to be a direct PDF
        """
        if not url:
            return False

        url_lower = url.lower()

        # Direct PDF file URLs
        if url_lower.endswith('.pdf'):
            return True

        # Known PDF serving patterns
        pdf_patterns = [
            '/pdf',
            'download',
            'content/pdf',
            '/article-pdf/',
            '/pdfviewer/',
        ]

        for pattern in pdf_patterns:
            if pattern in url_lower:
                return True

        return False

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
            logger.debug(f"[OpenAlex] No metadata found for {doi}")
            return None

        pdf_url = metadata.get('pdf_url')

        if pdf_url:
            logger.info(f"[OpenAlex] Found PDF for {doi}")
            logger.debug(f"[OpenAlex] PDF URL: {pdf_url}")
            return pdf_url
        else:
            logger.debug(f"[OpenAlex] No PDF URL available for {doi}")
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
