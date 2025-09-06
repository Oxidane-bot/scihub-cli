"""
Core downloader implementation with single responsibility.
"""

import requests
from typing import Optional, Tuple
from ..config.settings import settings
from ..network.session import BasicSession
from ..utils.logging import get_logger

logger = get_logger(__name__)

class FileDownloader:
    """Handles pure file downloading operations."""
    
    def __init__(self, session: Optional[requests.Session] = None, timeout: int = None):
        self.session = session or BasicSession(timeout or settings.timeout)
        self.timeout = timeout or settings.timeout
    
    def download_file(self, url: str, output_path: str) -> Tuple[bool, Optional[str]]:
        """Download a file from URL to output path."""
        try:
            logger.info(f"Downloading to {output_path}")
            response = self.session.get(url, timeout=self.timeout, stream=True)
            
            if response.status_code == 200:
                # Check content type
                content_type = response.headers.get('Content-Type', '')
                if 'pdf' not in content_type.lower() and 'octet-stream' not in content_type.lower():
                    logger.warning(f"Response is not a PDF: {content_type}")
                
                # Save the file
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=settings.CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
                
                return True, None
            else:
                error_msg = f"Failed to download file: HTTP {response.status_code}"
                logger.warning(error_msg)
                return False, error_msg
                
        except Exception as e:
            error_msg = f"Error downloading file: {e}"
            logger.error(error_msg)
            return False, error_msg
    
    def get_page_content(self, url: str) -> Tuple[Optional[str], Optional[int]]:
        """Get HTML content from a URL."""
        try:
            response = self.session.get(url, timeout=self.timeout)
            return response.text, response.status_code
        except Exception as e:
            logger.error(f"Error fetching page content: {e}")
            return None, None