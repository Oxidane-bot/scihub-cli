"""
Publication year detection using Crossref API.
"""

import requests

from ..config.settings import settings
from ..utils.logging import get_logger

logger = get_logger(__name__)


class YearDetector:
    """Detects publication year for DOIs using Crossref API."""

    def __init__(self):
        self.base_url = "https://api.crossref.org/works"
        self.cache: dict[str, int | None] = {}
        self.session = requests.Session()
        contact_email = settings.email or "scihub-cli@example.invalid"
        self.session.headers.update({"User-Agent": f"scihub-cli/1.0 (mailto:{contact_email})"})

    def get_year(self, doi: str) -> int | None:
        """
        Get publication year for a DOI.

        Args:
            doi: The DOI to look up

        Returns:
            Publication year as integer, or None if not found
        """
        # Check cache first
        if doi in self.cache:
            return self.cache[doi]

        try:
            url = f"{self.base_url}/{doi}"
            response = self.session.get(url, timeout=10)

            if response.status_code == 200:
                data = response.json()
                message = data.get("message", {})

                # Try multiple date fields (Crossref has several formats)
                year = None

                # Try 'published' field first
                if "published" in message:
                    date_parts = message["published"].get("date-parts", [[]])
                    if date_parts and date_parts[0]:
                        year = date_parts[0][0]

                # Fallback to 'created' field
                if not year and "created" in message:
                    date_time = message["created"].get("date-time", "")
                    if date_time:
                        year = int(date_time[:4])

                # Fallback to 'issued' field
                if not year and "issued" in message:
                    date_parts = message["issued"].get("date-parts", [[]])
                    if date_parts and date_parts[0]:
                        year = date_parts[0][0]

                if year:
                    logger.debug(f"Detected year {year} for DOI {doi}")
                    self.cache[doi] = year
                    return year
                else:
                    logger.warning(f"No year found in Crossref data for {doi}")
                    self.cache[doi] = None
                    return None

            else:
                logger.warning(f"Crossref API returned {response.status_code} for {doi}")
                self.cache[doi] = None
                return None

        except requests.RequestException as e:
            logger.warning(f"Failed to fetch year from Crossref for {doi}: {e}")
            self.cache[doi] = None
            return None
        except (KeyError, IndexError, ValueError) as e:
            logger.warning(f"Failed to parse year from Crossref response for {doi}: {e}")
            self.cache[doi] = None
            return None
