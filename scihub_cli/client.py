"""
Main Sci-Hub client providing high-level interface.
"""

import os
import time
from typing import List, Optional, Tuple
from .core.mirror_manager import MirrorManager
from .core.parser import ContentParser
from .core.doi_processor import DOIProcessor
from .core.file_manager import FileManager
from .core.downloader import FileDownloader
from .network.session import BasicSession
from .utils.retry import RetryConfig, retry_operation
from .utils.logging import get_logger
from .config.settings import settings

logger = get_logger(__name__)

class SciHubClient:
    """Main client interface for Sci-Hub operations with dependency injection."""
    
    def __init__(self,
                 output_dir: str = None,
                 mirrors: List[str] = None,
                 timeout: int = None,
                 retries: int = None,
                 mirror_manager: MirrorManager = None,
                 parser: ContentParser = None,
                 file_manager: FileManager = None,
                 downloader: FileDownloader = None):
        """Initialize client with optional dependency injection."""
        
        # Configuration
        self.output_dir = output_dir or settings.output_dir
        self.timeout = timeout or settings.timeout
        self.retry_config = RetryConfig(max_attempts=retries or settings.retries)
        
        # Dependency injection with defaults
        self.mirror_manager = mirror_manager or MirrorManager(mirrors, self.timeout)
        self.parser = parser or ContentParser()
        self.file_manager = file_manager or FileManager(self.output_dir)
        self.downloader = downloader or FileDownloader(BasicSession(self.timeout))
        
        # DOI processor (stateless)
        self.doi_processor = DOIProcessor()
    
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
        """Single download attempt."""
        # Get working mirror
        mirror = self.mirror_manager.get_working_mirror()
        
        # Format DOI for Sci-Hub URL if it's a DOI
        formatted_doi = (self.doi_processor.format_doi_for_url(doi) 
                        if doi.startswith('10.') else doi)
        
        # Construct Sci-Hub URL
        scihub_url = f"{mirror}/{formatted_doi}"
        logger.debug(f"Accessing Sci-Hub URL: {scihub_url}")
        
        # Get the Sci-Hub page
        html_content, status_code = self.downloader.get_page_content(scihub_url)
        if not html_content or status_code != 200:
            # Try fallback with original DOI format
            if doi.startswith('10.'):
                fallback_url = f"{mirror}/{doi}"
                logger.debug(f"Trying fallback URL: {fallback_url}")
                html_content, status_code = self.downloader.get_page_content(fallback_url)
                if not html_content or status_code != 200:
                    raise Exception(f"Failed to access Sci-Hub page: {status_code}")
            else:
                raise Exception(f"Failed to access Sci-Hub page: {status_code}")
        
        # Extract the download URL
        download_url = self.parser.extract_download_url(html_content, mirror)
        if not download_url:
            raise Exception(f"Could not extract download URL for {doi}")
        
        logger.debug(f"Download URL: {download_url}")
        
        # Generate filename and output path
        filename = self.file_manager.generate_filename(doi, html_content)
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