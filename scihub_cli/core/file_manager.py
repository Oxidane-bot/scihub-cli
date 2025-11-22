"""
File management and naming utilities.
"""

import os
import re
from typing import Optional
from ..config.settings import settings
from ..metadata_utils import extract_metadata, generate_filename_from_metadata
from ..utils.logging import get_logger

logger = get_logger(__name__)

class FileManager:
    """Handles file operations and naming."""
    
    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or settings.output_dir
        os.makedirs(self.output_dir, exist_ok=True)
    
    def generate_filename(self, doi: str, html_content: Optional[str] = None) -> str:
        """Generate a filename based on DOI and optionally paper metadata."""
        # Default filename based on DOI
        filename = self._clean_filename(doi.replace('/', '_'))
        
        # If we have HTML, try to extract metadata
        if html_content:
            metadata = extract_metadata(html_content)
            
            if metadata and 'title' in metadata and 'year' in metadata:
                return generate_filename_from_metadata(
                    metadata['title'],
                    metadata['year'],
                    doi
                )
            else:
                # Fallback to simple title extraction
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html_content, 'html.parser')
                
                title_elem = soup.find('title')
                if title_elem and title_elem.text and 'sci-hub' not in title_elem.text.lower():
                    title = title_elem.text.strip()
                    filename = self._clean_filename(title[:50])
        
        return f"{filename}.pdf"
    
    def get_output_path(self, filename: str) -> str:
        """Get full output path for a filename."""
        return os.path.join(self.output_dir, filename)
    
    def validate_file(self, file_path: str) -> bool:
        """Validate downloaded file."""
        if not os.path.exists(file_path):
            return False
        
        file_size = os.path.getsize(file_path)
        if file_size < settings.MIN_FILE_SIZE:
            logger.warning(f"Downloaded file is suspiciously small: {file_size} bytes")
            return False
        
        return True
    
    def _clean_filename(self, filename: str) -> str:
        """Create a safe filename from potentially unsafe string."""
        # Replace unsafe characters
        unsafe_chars = r'[<>:"/\\|?*]'
        filename = re.sub(unsafe_chars, '_', filename)
        
        # Limit length
        if len(filename) > settings.MAX_FILENAME_LENGTH:
            filename = filename[:settings.MAX_FILENAME_LENGTH]
        
        return filename