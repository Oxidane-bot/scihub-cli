"""
Main Sci-Hub client providing high-level interface with multi-source support.
"""

import os
import time
from typing import Optional

from .config.settings import settings
from .core.doi_processor import DOIProcessor
from .core.downloader import FileDownloader
from .core.file_manager import FileManager
from .core.mirror_manager import MirrorManager
from .core.parser import ContentParser
from .core.source_manager import SourceManager
from .network.session import BasicSession
from .sources.core_source import CORESource
from .sources.scihub_source import SciHubSource
from .sources.unpaywall_source import UnpaywallSource
from .utils.logging import get_logger
from .utils.retry import RetryConfig

logger = get_logger(__name__)


class SciHubClient:
    """Main client interface with multi-source support (Sci-Hub + Unpaywall)."""

    def __init__(
        self,
        output_dir: str = None,
        mirrors: list[str] = None,
        timeout: int = None,
        retries: int = None,
        email: str = None,
        mirror_manager: MirrorManager = None,
        parser: ContentParser = None,
        file_manager: FileManager = None,
        downloader: FileDownloader = None,
        source_manager: SourceManager = None,
    ):
        """Initialize client with optional dependency injection."""

        # Configuration
        self.output_dir = output_dir or settings.output_dir
        self.timeout = timeout or settings.timeout
        self.retry_config = RetryConfig(max_attempts=retries or settings.retries)
        self.email = email or settings.email

        # Dependency injection with defaults
        self.mirror_manager = mirror_manager or MirrorManager(mirrors, self.timeout)
        self.parser = parser or ContentParser()
        self.file_manager = file_manager or FileManager(self.output_dir)
        self.downloader = downloader or FileDownloader(BasicSession(self.timeout))

        # DOI processor (stateless)
        self.doi_processor = DOIProcessor()

        # Multi-source support
        if source_manager is None:
            # Initialize paper sources
            sources = [
                SciHubSource(
                    mirror_manager=self.mirror_manager,
                    parser=self.parser,
                    doi_processor=self.doi_processor,
                    downloader=self.downloader,
                )
            ]

            # Only enable Unpaywall when email is provided
            if self.email:
                sources.insert(0, UnpaywallSource(email=self.email, timeout=self.timeout))

            # CORE does not require email, keep as OA fallback
            sources.append(CORESource(api_key=settings.core_api_key, timeout=self.timeout))

            self.source_manager = SourceManager(
                sources=sources,
                year_threshold=settings.year_threshold,
                enable_year_routing=settings.enable_year_routing,
            )
        else:
            self.source_manager = source_manager

    def download_paper(self, identifier: str) -> Optional[str]:
        """
        Download a paper given its DOI or URL.

        Uses fine-grained retry at lower layers (download, API calls).
        No coarse-grained retry at this level.
        """
        doi = self.doi_processor.normalize_doi(identifier)
        logger.info(f"Downloading paper: {doi}")

        try:
            return self._download_single_paper(doi)
        except Exception as e:
            logger.error(f"Failed to download {doi}: {e}")
            return None

    def _download_single_paper(self, doi: str) -> str:
        """
        Single download attempt using multi-source manager.

        Gets URL and metadata in one pass to avoid duplicate API calls.
        """
        # Get PDF URL and metadata together (avoids duplicate API calls)
        download_url, metadata = self.source_manager.get_pdf_url_with_metadata(doi)

        if not download_url:
            raise Exception(f"Could not find PDF URL for {doi} from any source")

        logger.debug(f"Download URL: {download_url}")

        # Generate filename from metadata if available
        filename = self._generate_filename(doi, metadata)
        output_path = self.file_manager.get_output_path(filename)

        # Download the PDF (with automatic retry at download layer)
        success, error_msg = self.downloader.download_file(download_url, output_path)
        if not success:
            # If Sci-Hub download failed, invalidate mirror cache
            if "sci-hub" in download_url.lower():
                logger.warning("Sci-Hub download failed, invalidating mirror cache")
                scihub = [s for s in self.source_manager.sources.values() if s.name == "Sci-Hub"]
                if scihub:
                    scihub[0].mirror_manager.invalidate_cache()

            raise Exception(error_msg)

        # Validate file
        if not self.file_manager.validate_file(output_path):
            raise Exception("Downloaded file validation failed")

        file_size = os.path.getsize(output_path)
        logger.info(f"Successfully downloaded {doi} ({file_size} bytes)")
        return output_path

    def _generate_filename(self, doi: str, metadata: Optional[dict]) -> str:
        """
        Generate filename from metadata or DOI.

        Args:
            doi: The DOI
            metadata: Optional metadata dict from source

        Returns:
            Generated filename
        """
        if metadata and metadata.get("title"):
            try:
                from .metadata_utils import generate_filename_from_metadata

                return generate_filename_from_metadata(
                    metadata.get("title", ""), metadata.get("year", ""), doi
                )
            except Exception as e:
                logger.debug(f"Could not generate filename from metadata: {e}")

        # Fallback to DOI-based filename
        return self.file_manager.generate_filename(doi, html_content=None)

    def download_from_file(
        self, input_file: str, parallel: int = None
    ) -> list[tuple[str, Optional[str]]]:
        """Download papers from a file containing DOIs or URLs."""
        parallel = parallel or settings.parallel

        # Read input file
        try:
            with open(input_file, encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            logger.error(f"Error reading input file: {e}")
            return []

        # Filter out comments and empty lines
        identifiers = [
            line.strip() for line in lines if line.strip() and not line.strip().startswith("#")
        ]

        logger.info(f"Found {len(identifiers)} papers to download")

        # Download each paper (sequential for now, can be parallelized later)
        results = []
        for i, identifier in enumerate(identifiers):
            logger.info(f"Processing {i + 1}/{len(identifiers)}: {identifier}")
            result = self.download_paper(identifier)
            results.append((identifier, result))

            # Add a small delay between downloads
            if i < len(identifiers) - 1:
                time.sleep(2)

        # Print summary
        successful = sum(1 for _, result in results if result)
        logger.info(f"Downloaded {successful}/{len(identifiers)} papers")

        return results
