#!/usr/bin/env python3
"""
Sci-Hub Batch Downloader

A command-line tool to batch download academic papers from Sci-Hub.
"""

import argparse
import os
import re
import sys
import logging
import requests
from urllib.parse import urlparse, quote, unquote, urljoin
from bs4 import BeautifulSoup
import time
from pathlib import Path
from scihub_cli.metadata_utils import extract_metadata, generate_filename_from_metadata

# Default settings
DEFAULT_OUTPUT_DIR = './downloads'
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_PARALLEL = 3
# Mirror configuration by difficulty level (科学分层策略)
MIRROR_TIERS = {
    'easy': [  # No Cloudflare protection, use basic requests
        'https://www.sci-hub.ee',
        'https://sci-hub.ru', 
        'https://sci-hub.ren',
        'https://sci-hub.wf',
    ],
    'hard': [  # Strong Cloudflare protection, needs advanced bypass
        'https://sci-hub.se',  # The final boss
    ]
}

DEFAULT_MIRRORS = MIRROR_TIERS['easy'] + MIRROR_TIERS['hard']

# Use user's home directory for logs
user_home = str(Path.home())
log_dir = os.path.join(user_home, '.scihub-cli', 'logs')
os.makedirs(log_dir, exist_ok=True)

# Set up logging
# Attempt to reconfigure console for UTF-8 output on Windows
if sys.platform == "win32":
    try:
        if sys.stdout.isatty() and sys.stdout.encoding.lower() != 'utf-8':
            sys.stdout.reconfigure(encoding='utf-8')
        if sys.stderr.isatty() and sys.stderr.encoding.lower() != 'utf-8':
            sys.stderr.reconfigure(encoding='utf-8')
    except Exception as e:
        # Use print for this warning as logger might not be fully configured or could also cause issues
        print(f"Warning: Could not reconfigure console to UTF-8: {e}", file=sys.stderr)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(os.path.join(log_dir, 'scihub-dl.log'), encoding='utf-8'), # Explicitly use UTF-8 for file
        logging.StreamHandler(sys.stdout) # sys.stdout should now be UTF-8 if reconfigure worked
    ]
)
logger = logging.getLogger(__name__)

class SciHubDownloader:
    """Class to handle downloading papers from Sci-Hub."""
    
    def __init__(self, output_dir=DEFAULT_OUTPUT_DIR, mirror=None, 
                 timeout=DEFAULT_TIMEOUT, retries=DEFAULT_RETRIES):
        """Initialize the downloader with settings."""
        self.output_dir = output_dir
        self.mirrors = DEFAULT_MIRRORS if mirror is None else [mirror]
        self.timeout = timeout
        self.retries = retries
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
    
    def _get_working_mirror(self):
        """Try mirrors with tiered strategy: easy first, then hard."""
        
        # Tier 1: Easy mirrors first (fastest)
        logger.info("[Tier 1] Trying easy mirrors first...")
        for mirror in MIRROR_TIERS['easy']:
            try:
                response = self.session.get(mirror, timeout=self.timeout)
                if response.status_code == 200:
                    logger.info(f"SUCCESS: Using easy mirror: {mirror}")
                    return mirror
                else:
                    logger.debug(f"FAIL: {mirror} returned {response.status_code}")
            except requests.RequestException as e:
                logger.debug(f"FAIL: {mirror} failed: {e}")
        
        # Tier 2: Hard mirrors (sci-hub.se) as last resort
        logger.info("[Tier 2] Easy mirrors failed, trying hard mirrors...")
        for mirror in MIRROR_TIERS['hard']:
            try:
                response = self.session.get(mirror, timeout=self.timeout)
                if response.status_code == 200:
                    logger.info(f"SUCCESS: Using hard mirror: {mirror}")
                    return mirror
                elif response.status_code == 403:
                    logger.warning(f"PROTECTED: {mirror} is 403 protected, but might work for downloads")
                    return mirror  # Return anyway, might work for actual downloads
                else:
                    logger.debug(f"FAIL: {mirror} returned {response.status_code}")
            except requests.RequestException as e:
                logger.debug(f"FAIL: {mirror} failed: {e}")
        
        raise Exception("All mirrors are unavailable")
    
    def _normalize_doi(self, identifier):
        """Convert URL or DOI to a normalized DOI format."""
        # If it's already a DOI
        doi_pattern = r'\b10\.\d{4,}(?:\.\d+)*\/(?:(?!["&\'<>])\S)+\b'
        if re.match(doi_pattern, identifier):
            return identifier
        
        # If it's a URL, try to extract DOI
        parsed = urlparse(identifier)
        if parsed.netloc:
            path = parsed.path
            # Extract DOI from common URL patterns
            if 'doi.org' in parsed.netloc:
                return path.strip('/')
            
            # Try to find DOI in the URL path
            doi_match = re.search(doi_pattern, identifier)
            if doi_match:
                return doi_match.group(0)
        
        # Return as is if we can't normalize
        return identifier
    
    def _format_doi_for_url(self, doi):
        """Format DOI for use in Sci-Hub URL."""
        # Replace / with @ for Sci-Hub URL format
        formatted = doi.replace('/', '@')
        # Handle parentheses and other special characters
        formatted = quote(formatted, safe='@')
        return formatted
    
    def _clean_url(self, url):
        """Clean the URL by removing fragments and adding download parameter."""
        # Remove the fragment (anything after #)
        if '#' in url:
            url = url.split('#')[0]
        
        # Add the download parameter if not already present
        if "download=true" not in url:
            url += ("&" if "?" in url else "?") + "download=true"
            
        return url
    
    def _fix_url_format(self, url, mirror):
        """Fix common URL formatting issues."""
        # Handle relative URLs (starting with /)
        if url.startswith('/'):
            # Extract domain from mirror
            parsed_mirror = urlparse(mirror)
            base_url = f"{parsed_mirror.scheme}://{parsed_mirror.netloc}"
            return urljoin(base_url, url)
        
        # Handle relative URLs without leading slash
        if not url.startswith('http') and '://' not in url:
            return urljoin(mirror, url)
        
        # Handle incorrectly formatted domain (sci-hub.sedownloads)
        parsed = urlparse(url)
        if 'downloads' in parsed.netloc:
            domain = parsed.netloc.split('downloads')[0]
            path = f"/downloads{parsed.netloc.split('downloads')[1]}{parsed.path}"
            query = f"?{parsed.query}" if parsed.query else ""
            return f"https://{domain}{path}{query}"
        
        return url
    
    def _extract_download_url(self, html_content, mirror):
        """Extract the PDF download URL from Sci-Hub HTML."""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Look for the download button (onclick attribute)
        button_pattern = r"location\.href=['\"]([^'\"]+)['\"]"
        buttons = soup.find_all('button', onclick=re.compile(button_pattern))
        for button in buttons:
            onclick = button.get('onclick', '')
            match = re.search(button_pattern, onclick)
            if match:
                href = match.group(1)
                href = self._fix_url_format(href, mirror)
                logger.debug(f"Found download button (onclick): {href}")
                return self._clean_url(href)
        
        # Look for the download button or iframe
        iframe = soup.find('iframe', id='pdf')
        if iframe and iframe.get('src'):
            src = iframe.get('src')
            # Handle URL formatting
            src = self._fix_url_format(src, mirror)
            logger.debug(f"Found download iframe: {src}")
            return self._clean_url(src)
            
        # Look for download button
        download_button = soup.find('a', string=re.compile(r'download', re.I))
        if download_button and download_button.get('href'):
            href = download_button.get('href')
            href = self._fix_url_format(href, mirror)
            logger.debug(f"Found download button: {href}")
            return self._clean_url(href)
            
        # Look for embed tags
        embed = soup.find('embed', attrs={'type': 'application/pdf'})
        if embed and embed.get('src'):
            src = embed.get('src')
            src = self._fix_url_format(src, mirror)
            logger.debug(f"Found embedded PDF: {src}")
            return self._clean_url(src)
        
        # Search directly in the HTML content for download patterns
        # Look for specific download links in JavaScript or HTML
        patterns = [
            r"location\.href=['\"]([^'\"]+)['\"]",
            r'href=["\'](/downloads/[^"\']+)["\']',
            r'src=["\'](/downloads/[^"\']+\.pdf)["\']',
            r'/downloads/[^"\'<>\s]+\.pdf'
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, html_content)
            if matches:
                download_link = matches[0]
                # Clean up the link
                if isinstance(download_link, tuple):
                    download_link = download_link[0]
                download_link = download_link.split('#')[0] if '#' in download_link else download_link
                full_url = self._fix_url_format(download_link, mirror)
                logger.debug(f"Found download link with pattern {pattern}: {full_url}")
                return self._clean_url(full_url)
        
        logger.warning("Could not find download URL in HTML")
        return None
    
    def _clean_filename(self, filename):
        """Create a safe filename from potentially unsafe string."""
        # Replace unsafe characters
        unsafe_chars = r'[<>:"/\\|?*]'
        filename = re.sub(unsafe_chars, '_', filename)
        # Limit length
        if len(filename) > 100:
            filename = filename[:100]
        return filename
    
    def _generate_filename(self, doi, html_content=None):
        """Generate a filename based on DOI and optionally paper metadata."""
        # Default filename based on DOI
        filename = self._clean_filename(doi.replace('/', '_'))
        
        # If we have HTML, try to extract metadata using the new metadata utilities
        if html_content:
            # Try to extract metadata (title and year)
            metadata = extract_metadata(html_content)
            
            if metadata and 'title' in metadata and 'year' in metadata:
                # Generate filename from metadata
                return generate_filename_from_metadata(
                    metadata['title'],
                    metadata['year'],
                    doi
                )
            else:
                # Fallback to the original method if metadata extraction failed
                soup = BeautifulSoup(html_content, 'html.parser')
                
                # Try to get title
                title_elem = soup.find('title')
                if title_elem and title_elem.text and 'sci-hub' not in title_elem.text.lower():
                    title = title_elem.text.strip()
                    filename = self._clean_filename(title[:50])
                
        return f"{filename}.pdf"
    
    def download_paper(self, identifier):
        """Download a paper given its DOI or URL."""
        doi = self._normalize_doi(identifier)
        logger.info(f"Downloading paper with identifier: {doi}")
        
        # Try to download with retries
        for attempt in range(self.retries):
            try:
                # Get working mirror
                mirror = self._get_working_mirror()
                
                # Format DOI for Sci-Hub URL if it's a DOI
                formatted_doi = self._format_doi_for_url(doi) if doi.startswith('10.') else doi
                
                # Construct Sci-Hub URL
                scihub_url = f"{mirror}/{formatted_doi}"
                logger.debug(f"Accessing Sci-Hub URL: {scihub_url}")
                
                # Get the Sci-Hub page
                response = self.session.get(scihub_url, timeout=self.timeout)
                if response.status_code != 200:
                    logger.warning(f"Failed to access Sci-Hub page: {response.status_code}")
                    continue
                
                # Extract the download URL
                download_url = self._extract_download_url(response.text, mirror)
                if not download_url:
                    logger.warning(f"Could not extract download URL for {doi}")
                    
                    # Try using the original DOI format as a fallback
                    if doi.startswith('10.'):
                        fallback_url = f"{mirror}/{doi}"
                        logger.debug(f"Trying fallback URL without formatting: {fallback_url}")
                        fallback_response = self.session.get(fallback_url, timeout=self.timeout)
                        if fallback_response.status_code == 200:
                            download_url = self._extract_download_url(fallback_response.text, mirror)
                            if not download_url:
                                logger.warning(f"Fallback attempt also failed for {doi}")
                                time.sleep(1)
                                continue
                        else:
                            logger.warning(f"Fallback URL failed: {fallback_response.status_code}")
                            time.sleep(1)
                            continue
                    else:
                        time.sleep(1)
                        continue
                
                logger.debug(f"Download URL: {download_url}")
                
                # Generate filename
                # If we're using fallback_response, use its content for metadata extraction
                html_content = fallback_response.text if 'fallback_response' in locals() else response.text
                filename = self._generate_filename(doi, html_content)
                output_path = os.path.join(self.output_dir, filename)
                
                # Download the PDF
                logger.info(f"Downloading to {output_path}")
                pdf_response = self.session.get(download_url, timeout=self.timeout, stream=True)
                
                if pdf_response.status_code == 200:
                    # Check content type
                    content_type = pdf_response.headers.get('Content-Type', '')
                    if 'pdf' not in content_type.lower() and 'octet-stream' not in content_type.lower():
                        logger.warning(f"Response is not a PDF: {content_type}")
                        # Continue anyway as sometimes content-type is not set correctly
                    
                    # Save the PDF
                    with open(output_path, 'wb') as f:
                        for chunk in pdf_response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                    
                    # Verify file size
                    file_size = os.path.getsize(output_path)
                    if file_size < 10000:  # Less than 10KB is suspicious
                        logger.warning(f"Downloaded file is suspiciously small: {file_size} bytes")
                        if attempt < self.retries - 1:
                            continue
                    
                    logger.info(f"Successfully downloaded {doi} ({file_size} bytes)")
                    return output_path
                else:
                    logger.warning(f"Failed to download PDF: {pdf_response.status_code}")
            
            except Exception as e:
                logger.error(f"Error downloading {doi}: {e}")
            
            # Wait before retry
            wait_time = (attempt + 1) * 2
            logger.info(f"Retrying in {wait_time} seconds... (Attempt {attempt+1}/{self.retries})")
            time.sleep(wait_time)
        
        logger.error(f"Failed to download {doi} after {self.retries} attempts")
        return None
    
    def download_from_file(self, input_file, parallel=DEFAULT_PARALLEL):
        """Download papers from a file containing DOIs or URLs."""
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
        
        # Download each paper
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


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(description='Download academic papers from Sci-Hub in batch mode.')
    
    parser.add_argument('input_file', help='Text file containing DOIs or URLs (one per line)')
    parser.add_argument('-o', '--output', default=DEFAULT_OUTPUT_DIR,
                        help=f'Output directory for downloaded PDFs (default: {DEFAULT_OUTPUT_DIR})')
    parser.add_argument('-m', '--mirror', help='Specific Sci-Hub mirror to use')
    parser.add_argument('-t', '--timeout', type=int, default=DEFAULT_TIMEOUT,
                        help=f'Request timeout in seconds (default: {DEFAULT_TIMEOUT})')
    parser.add_argument('-r', '--retries', type=int, default=DEFAULT_RETRIES,
                        help=f'Number of retries for failed downloads (default: {DEFAULT_RETRIES})')
    parser.add_argument('-p', '--parallel', type=int, default=DEFAULT_PARALLEL,
                        help=f'Number of parallel downloads (default: {DEFAULT_PARALLEL})')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Enable verbose logging')
    parser.add_argument('--version', action='version', version='Sci-Hub Downloader 0.1.0')
    
    args = parser.parse_args()
    
    # Set logging level
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    # Initialize downloader
    downloader = SciHubDownloader(
        output_dir=args.output,
        mirror=args.mirror,
        timeout=args.timeout,
        retries=args.retries
    )
    
    # Download papers
    try:
        results = downloader.download_from_file(args.input_file, args.parallel)
        
        # Print failures if any
        failures = [(identifier, result) for identifier, result in results if not result]
        if failures:
            logger.warning("The following papers failed to download:")
            for identifier, _ in failures:
                logger.warning(f"  - {identifier}")
        
        return 0 if len(failures) == 0 else 1
    
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return 1


if __name__ == '__main__':
    sys.exit(main()) 