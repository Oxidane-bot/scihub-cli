"""
Unpaywall source implementation.
"""

import requests
from typing import Optional, Dict
from .base import PaperSource
from ..utils.logging import get_logger

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
        self.session.headers.update({
            'User-Agent': f'scihub-cli/1.0 (mailto:{email})'
        })

    @property
    def name(self) -> str:
        return "Unpaywall"

    def can_handle(self, doi: str) -> bool:
        """Unpaywall can query any DOI, but only returns OA articles."""
        return doi.startswith('10.')

    def get_pdf_url(self, doi: str) -> Optional[str]:
        """
        Get PDF download URL from Unpaywall.

        Args:
            doi: The DOI to look up

        Returns:
            PDF URL if open access is available, None otherwise
        """
        try:
            url = f"{self.base_url}/{doi}"
            params = {"email": self.email}

            logger.debug(f"[Unpaywall] Querying: {doi}")
            response = self.session.get(url, params=params, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json()

                # Check if paper is open access
                if not data.get("is_oa"):
                    logger.debug(f"[Unpaywall] Paper {doi} is not open access")
                    return None

                # Get best OA location
                best_oa = data.get("best_oa_location")
                if not best_oa:
                    logger.warning(f"[Unpaywall] No OA location found for {doi}")
                    return None

                # Get PDF URL
                pdf_url = best_oa.get("url_for_pdf") or best_oa.get("url")
                if pdf_url:
                    oa_status = data.get("oa_status", "unknown")
                    logger.info(f"[Unpaywall] Found OA paper (status: {oa_status}): {doi}")
                    logger.debug(f"[Unpaywall] PDF URL: {pdf_url}")
                    return pdf_url
                else:
                    logger.warning(f"[Unpaywall] No PDF URL in OA location for {doi}")
                    return None

            elif response.status_code == 404:
                logger.debug(f"[Unpaywall] DOI not found: {doi}")
                return None
            else:
                logger.warning(f"[Unpaywall] API returned {response.status_code} for {doi}")
                return None

        except requests.Timeout:
            logger.warning(f"[Unpaywall] Request timeout for {doi}")
            return None
        except requests.RequestException as e:
            logger.warning(f"[Unpaywall] Request error for {doi}: {e}")
            return None
        except (KeyError, ValueError) as e:
            logger.warning(f"[Unpaywall] Error parsing response for {doi}: {e}")
            return None

    def get_metadata(self, doi: str) -> Optional[Dict[str, str]]:
        """
        Get metadata from Unpaywall.

        Args:
            doi: The DOI to look up

        Returns:
            Dictionary with title, year, etc. or None
        """
        try:
            url = f"{self.base_url}/{doi}"
            params = {"email": self.email}

            response = self.session.get(url, params=params, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json()
                return {
                    "title": data.get("title", ""),
                    "year": str(data.get("year", "")),
                    "journal": data.get("journal_name", ""),
                    "is_oa": data.get("is_oa", False),
                    "oa_status": data.get("oa_status", "")
                }
            else:
                return None

        except Exception as e:
            logger.debug(f"[Unpaywall] Error getting metadata for {doi}: {e}")
            return None
