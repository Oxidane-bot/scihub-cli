"""
Sci-Hub source implementation.
"""

from typing import Optional
from .base import PaperSource
from ..core.mirror_manager import MirrorManager
from ..core.parser import ContentParser
from ..core.doi_processor import DOIProcessor
from ..core.downloader import FileDownloader
from ..utils.logging import get_logger

logger = get_logger(__name__)


class SciHubSource(PaperSource):
    """Sci-Hub paper source."""

    def __init__(self,
                 mirror_manager: MirrorManager,
                 parser: ContentParser,
                 doi_processor: DOIProcessor,
                 downloader: FileDownloader):
        """
        Initialize Sci-Hub source.

        Args:
            mirror_manager: Mirror management instance
            parser: HTML parser instance
            doi_processor: DOI processor instance
            downloader: File downloader instance
        """
        self.mirror_manager = mirror_manager
        self.parser = parser
        self.doi_processor = doi_processor
        self.downloader = downloader

    @property
    def name(self) -> str:
        return "Sci-Hub"

    def can_handle(self, doi: str) -> bool:
        """Sci-Hub can potentially handle any DOI."""
        return True

    def get_pdf_url(self, doi: str) -> Optional[str]:
        """
        Get PDF download URL from Sci-Hub.

        Args:
            doi: The DOI to look up

        Returns:
            PDF URL if found, None otherwise
        """
        try:
            # Get working mirror
            mirror = self.mirror_manager.get_working_mirror()

            # Format DOI for Sci-Hub URL if it's a DOI
            formatted_doi = (self.doi_processor.format_doi_for_url(doi)
                            if doi.startswith('10.') else doi)

            # Construct Sci-Hub URL
            scihub_url = f"{mirror}/{formatted_doi}"
            logger.debug(f"[Sci-Hub] Accessing: {scihub_url}")

            # Get the Sci-Hub page
            html_content, status_code = self.downloader.get_page_content(scihub_url)
            if not html_content or status_code != 200:
                # Try fallback with original DOI format
                if doi.startswith('10.'):
                    fallback_url = f"{mirror}/{doi}"
                    logger.debug(f"[Sci-Hub] Trying fallback: {fallback_url}")
                    html_content, status_code = self.downloader.get_page_content(fallback_url)
                    if not html_content or status_code != 200:
                        logger.warning(f"[Sci-Hub] Failed to access page: {status_code}")
                        return None
                else:
                    logger.warning(f"[Sci-Hub] Failed to access page: {status_code}")
                    return None

            # Extract the download URL
            download_url = self.parser.extract_download_url(html_content, mirror)
            if not download_url:
                # Try fallback with original DOI format if extraction failed
                if doi.startswith('10.'):
                    fallback_url = f"{mirror}/{doi}"
                    logger.debug(f"[Sci-Hub] Extraction failed, trying fallback: {fallback_url}")
                    html_content, status_code = self.downloader.get_page_content(fallback_url)
                    if html_content and status_code == 200:
                        download_url = self.parser.extract_download_url(html_content, mirror)

            if download_url:
                logger.debug(f"[Sci-Hub] Found PDF URL: {download_url}")
            else:
                logger.warning(f"[Sci-Hub] Could not extract download URL for {doi}")

            return download_url

        except Exception as e:
            logger.warning(f"[Sci-Hub] Error getting PDF URL for {doi}: {e}")
            return None
