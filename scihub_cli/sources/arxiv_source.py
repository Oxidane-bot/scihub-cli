"""
arXiv source implementation.
"""

import re
from typing import Optional
from urllib.parse import urlparse

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


class ArxivSource(PaperSource):
    """arXiv preprint source."""

    def __init__(self, timeout: int = 30):
        """
        Initialize arXiv source.

        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "scihub-cli/1.0"})

        # Metadata caching
        self._metadata_cache: dict[str, Optional[dict]] = {}

        # Retry configuration for API calls
        self.retry_config = APIRetryConfig()

    @property
    def name(self) -> str:
        return "arXiv"

    def can_handle(self, identifier: str) -> bool:
        """
        Check if this identifier is an arXiv paper.

        Supports formats:
        - arXiv:YYMM.NNNNN (e.g., arXiv:2401.12345)
        - YYMM.NNNNN (e.g., 2401.12345)
        - YYMM.NNNNNvN (e.g., 2401.12345v1)
        - Old format: YYMM.NNNN (4 digits, pre-2015)
        """
        arxiv_id = self._extract_arxiv_id(identifier)
        return arxiv_id is not None

    def get_pdf_url(self, identifier: str) -> Optional[str]:
        """
        Get PDF download URL from arXiv.

        Args:
            identifier: The arXiv ID or identifier

        Returns:
            PDF URL if valid arXiv paper, None otherwise
        """
        arxiv_id = self._extract_arxiv_id(identifier)
        if not arxiv_id:
            return None

        # arXiv PDF URL is predictable
        pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"

        # Verify the PDF exists by doing a HEAD request
        try:
            response = self.session.head(pdf_url, timeout=self.timeout, allow_redirects=True)
            if response.status_code == 200:
                logger.info(f"[arXiv] Found paper: {arxiv_id}")
                return pdf_url
            else:
                logger.warning(f"[arXiv] Paper not found: {arxiv_id} (HTTP {response.status_code})")
                return None
        except requests.RequestException as e:
            logger.warning(f"[arXiv] Failed to verify PDF for {arxiv_id}: {e}")
            return None

    def get_metadata(self, identifier: str) -> Optional[dict[str, str]]:
        """
        Get metadata from arXiv API.

        Args:
            identifier: The arXiv ID or identifier

        Returns:
            Dictionary with title, year, etc. or None
        """
        arxiv_id = self._extract_arxiv_id(identifier)
        if not arxiv_id:
            return None

        # Check cache first
        if arxiv_id in self._metadata_cache:
            logger.debug(f"[arXiv] Using cached metadata for {arxiv_id}")
            return self._metadata_cache[arxiv_id]

        # Fetch metadata from API
        logger.debug(f"[arXiv] Fetching metadata for {arxiv_id}")

        def _attempt_fetch():
            return self._fetch_from_api(arxiv_id)

        try:
            metadata = retry_with_classification(
                _attempt_fetch, self.retry_config, f"arXiv API for {arxiv_id}"
            )
            # Cache result (even if None)
            self._metadata_cache[arxiv_id] = metadata
            return metadata
        except PermanentError:
            # Cache permanent failures too
            self._metadata_cache[arxiv_id] = None
            return None
        except Exception:
            # Don't cache transient failures that exhausted retries
            return None

    def _fetch_from_api(self, arxiv_id: str) -> Optional[dict[str, str]]:
        """
        Single API fetch attempt with error classification.

        Args:
            arxiv_id: The arXiv ID to look up

        Returns:
            Dictionary with metadata

        Raises:
            PermanentError: For 404 or invalid ID
            RetryableError: For timeouts, rate limits, server errors
        """
        try:
            # arXiv API query
            url = "http://export.arxiv.org/api/query"
            params = {"id_list": arxiv_id, "max_results": 1}

            response = self.session.get(url, params=params, timeout=self.timeout)

            if response.status_code == 200:
                # Parse Atom XML response
                import xml.etree.ElementTree as ET

                root = ET.fromstring(response.content)

                # Namespace for Atom feed
                ns = {"atom": "http://www.w3.org/2005/Atom"}

                # Find the entry
                entry = root.find("atom:entry", ns)
                if entry is None:
                    logger.debug(f"[arXiv] No entry found for {arxiv_id}")
                    raise PermanentError("arXiv ID not found")

                # Extract metadata
                title_elem = entry.find("atom:title", ns)
                published_elem = entry.find("atom:published", ns)

                title = title_elem.text.strip() if title_elem is not None else ""
                published = published_elem.text if published_elem is not None else ""

                # Extract year from published date (format: YYYY-MM-DDTHH:MM:SSZ)
                year = None
                if published:
                    year_match = re.match(r"(\d{4})", published)
                    if year_match:
                        year = int(year_match.group(1))

                return {"title": title, "year": year, "source": "arXiv"}

            elif response.status_code == 429:
                logger.warning(f"[arXiv] Rate limited for {arxiv_id}")
                raise RetryableError("Rate limited")

            elif response.status_code >= 500:
                logger.warning(f"[arXiv] Server error {response.status_code} for {arxiv_id}")
                raise RetryableError(f"Server error {response.status_code}")

            else:
                logger.warning(f"[arXiv] API returned {response.status_code} for {arxiv_id}")
                raise PermanentError(f"Unexpected status {response.status_code}")

        except requests.Timeout as e:
            logger.warning(f"[arXiv] Request timeout for {arxiv_id}")
            raise RetryableError("Request timeout") from e

        except requests.RequestException as e:
            logger.warning(f"[arXiv] Request error for {arxiv_id}: {e}")
            raise RetryableError(f"Request error: {e}") from e

        except Exception as e:
            logger.warning(f"[arXiv] Error parsing response for {arxiv_id}: {e}")
            raise PermanentError(f"Parse error: {e}") from e

    def _extract_arxiv_id(self, identifier: str) -> Optional[str]:
        """
        Extract arXiv ID from various formats.

        Supports:
        - arXiv:YYMM.NNNNN
        - YYMM.NNNNN
        - YYMM.NNNNNvN (with version)
        - Old format: YYMM.NNNN (pre-2015)

        Args:
            identifier: The input identifier

        Returns:
            Clean arXiv ID (without 'arXiv:' prefix) or None
        """
        # Remove 'arxiv:' prefix if present (case insensitive)
        clean = re.sub(r"^arxiv:", "", identifier, flags=re.IGNORECASE).strip()

        # Extract from arXiv URLs (abs/pdf/e-print)
        parsed = urlparse(clean)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            domain = parsed.netloc.lower()
            if "arxiv.org" in domain:
                path = parsed.path.lstrip("/")
                for prefix in ("abs/", "pdf/", "e-print/"):
                    if path.startswith(prefix):
                        candidate = path[len(prefix) :]
                        if candidate.endswith(".pdf"):
                            candidate = candidate[: -len(".pdf")]
                        clean = candidate
                        break

        # New format (2015+): YYMM.NNNNN or YYMM.NNNNNvN
        if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", clean):
            return clean

        # Old format (pre-2015): YYMM.NNNN (4 digits)
        if re.match(r"^\d{4}\.\d{4}(v\d+)?$", clean):
            return clean

        return None
