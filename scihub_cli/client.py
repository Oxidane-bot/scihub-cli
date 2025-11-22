"""
Main Sci-Hub client providing high-level interface with multi-source support.
"""

import os
import time
from typing import List, Optional, Tuple
from .core.mirror_manager import MirrorManager
from .core.parser import ContentParser
from .core.doi_processor import DOIProcessor
from .core.file_manager import FileManager
from .core.downloader import FileDownloader
from .core.source_manager import SourceManager
from .network.session import BasicSession
from .sources.scihub_source import SciHubSource
from .sources.unpaywall_source import UnpaywallSource
from .utils.retry import RetryConfig, retry_operation
from .utils.logging import get_logger
from .config.settings import settings

logger = get_logger(__name__)

class SciHubClient:
    """Main client interface with multi-source support (Sci-Hub + Unpaywall)."""

    def __init__(self,
                 output_dir: str = None,
                 mirrors: List[str] = None,
                 timeout: int = None,
                 retries: int = None,
                 email: str = None,
                 mirror_manager: MirrorManager = None,
                 parser: ContentParser = None,
                 file_manager: FileManager = None,
                 downloader: FileDownloader = None,
                 source_manager: SourceManager = None):
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
            scihub_source = SciHubSource(
                mirror_manager=self.mirror_manager,
                parser=self.parser,
                doi_processor=self.doi_processor,
                downloader=self.downloader
            )
            unpaywall_source = UnpaywallSource(
                email=self.email,
                timeout=self.timeout
            )

            # Create source manager with intelligent routing
            self.source_manager = SourceManager(
                sources=[scihub_source, unpaywall_source],
                year_threshold=settings.year_threshold,
                enable_year_routing=settings.enable_year_routing
            )
        else:
            self.source_manager = source_manager
    
    def download_paper(self, identifier: str) -> Optional[str]:
        """Download a paper given its DOI or URL."""
        doi = self.doi_processor.normalize_doi(identifier)
        logger.info(f"Downloading paper with identifier: {doi}")
        
        def _download_operation():
            return self._download_single_paper(doi)
        
        try:
            return retry_operation(
                _download_operation,
                self.retry_config,
                f"download paper {doi}"
            )
        except Exception as e:
            logger.error(f"Failed to download {doi} after all retries: {e}")
            return None
    
    def _download_single_paper(self, doi: str) -> str:
        """Single download attempt using multi-source manager."""
        # Get PDF URL from any available source (intelligent routing)
        download_url = self.source_manager.get_pdf_url(doi)

        if not download_url:
            raise Exception(f"Could not find PDF URL for {doi} from any source")

        logger.debug(f"Download URL: {download_url}")

        # Generate filename
        # Try to get metadata from Unpaywall for better filenames
        filename = None
        try:
            unpaywall = [s for s in self.source_manager.sources.values() if s.name == "Unpaywall"]
            if unpaywall:
                metadata = unpaywall[0].get_metadata(doi)
                if metadata and metadata.get("title"):
                    from .metadata_utils import generate_filename_from_metadata
                    filename = generate_filename_from_metadata(
                        metadata.get("title", ""),
                        metadata.get("year", ""),
                        doi
                    )
        except Exception as e:
            logger.debug(f"Could not get metadata from Unpaywall: {e}")

        # Fallback to DOI-based filename if metadata extraction failed
        if not filename:
            filename = self.file_manager.generate_filename(doi, html_content=None)

        output_path = self.file_manager.get_output_path(filename)

        # Download the PDF
        success, error_msg = self.downloader.download_file(download_url, output_path)
        if not success:
            raise Exception(error_msg)

        # Validate file
        if not self.file_manager.validate_file(output_path):
            raise Exception("Downloaded file validation failed")

        file_size = os.path.getsize(output_path)
        logger.info(f"Successfully downloaded {doi} ({file_size} bytes)")
        return output_path
    
    def download_from_file(self, input_file: str, parallel: int = None) -> List[Tuple[str, Optional[str]]]:
        """Download papers from a file containing DOIs or URLs."""
        parallel = parallel or settings.parallel
        
        # Read input file
        try:
            with open(input_file, 'r') as f:
                lines = f.readlines()
        except Exception as e:
            logger.error(f"Error reading input file: {e}")
            return []
        
        # Filter out comments and empty lines
        identifiers = [line.strip() for line in lines 
                      if line.strip() and not line.strip().startswith('#')]
        
        logger.info(f"Found {len(identifiers)} papers to download")
        
        # Download each paper (sequential for now, can be parallelized later)
        results = []
        for i, identifier in enumerate(identifiers):
            logger.info(f"Processing {i+1}/{len(identifiers)}: {identifier}")
            result = self.download_paper(identifier)
            results.append((identifier, result))
            
            # Add a small delay between downloads
            if i < len(identifiers) - 1:
                time.sleep(2)
        
        # Print summary
        successful = sum(1 for _, result in results if result)
        logger.info(f"Downloaded {successful}/{len(identifiers)} papers")
        
        return results