"""
Core downloader implementation with single responsibility.
"""

import requests
import time
from typing import Optional, Tuple
from ..config.settings import settings
from ..network.session import BasicSession
from ..utils.logging import get_logger
from ..utils.retry import DownloadRetryConfig, RetryableException, PermanentException, retry_with_classification

logger = get_logger(__name__)

class FileDownloader:
    """Handles pure file downloading operations."""

    def __init__(self, session: Optional[requests.Session] = None, timeout: int = None):
        self.session = session or BasicSession(timeout or settings.timeout)
        self.timeout = timeout or settings.timeout

        # Retry configuration for downloads
        self.retry_config = DownloadRetryConfig()

        # Rate limiting for curl_cffi bypass (per-domain)
        self._last_bypass_time = {}  # domain -> timestamp
        self._bypass_delay = 2.0  # seconds between bypass requests to same domain
    
    def download_file(self, url: str, output_path: str) -> Tuple[bool, Optional[str]]:
        """
        Download a file from URL to output path with automatic retry.

        Args:
            url: URL to download from
            output_path: Path to save file

        Returns:
            Tuple of (success: bool, error_msg: Optional[str])
        """
        logger.info(f"Downloading to {output_path}")

        def _attempt_download():
            return self._download_once(url, output_path)

        try:
            return retry_with_classification(
                _attempt_download,
                self.retry_config,
                f"download from {url}"
            )
        except PermanentException as e:
            # Check if it's a 403 error - might be CDN protection
            error_msg = str(e)
            if '403' in error_msg:
                logger.warning(f"Got 403 error, attempting curl_cffi bypass...")
                success, bypass_error = self._download_with_curl_cffi(url, output_path)
                if success:
                    logger.info("Successfully downloaded using curl_cffi bypass")
                    return True, None
                else:
                    logger.warning(f"curl_cffi bypass also failed: {bypass_error}")

            # Don't retry permanent failures
            logger.error(f"Permanent failure: {error_msg}")
            return False, error_msg
        except Exception as e:
            # All retries exhausted
            error_msg = str(e)
            logger.error(f"Download failed after all retries: {error_msg}")
            return False, error_msg

    def _download_once(self, url: str, output_path: str) -> Tuple[bool, Optional[str]]:
        """
        Single download attempt with error classification.

        Raises:
            PermanentException: For 404, 403, invalid PDF content
            RetryableException: For timeouts, 5xx errors, connection issues
        """
        import tempfile
        import os
        import shutil

        try:
            response = self.session.get(url, timeout=self.timeout, stream=True)

            # Classify HTTP errors
            if response.status_code == 404:
                raise PermanentException("File not found (404)")
            elif response.status_code == 403:
                raise PermanentException("Access denied (403)")
            elif response.status_code >= 500:
                raise RetryableException(f"Server error ({response.status_code})")
            elif response.status_code != 200:
                raise PermanentException(f"HTTP {response.status_code}")

            # Check content type
            content_type = response.headers.get('Content-Type', '')
            if 'pdf' not in content_type.lower() and 'octet-stream' not in content_type.lower():
                logger.warning(f"Response is not a PDF: {content_type}")
                # If it's clearly HTML, reject it (permanent)
                if 'html' in content_type.lower():
                    raise PermanentException(f"Server returned HTML instead of PDF (Content-Type: {content_type})")

            # Download to temporary location first
            temp_fd, temp_path = tempfile.mkstemp(suffix='.pdf')

            try:
                with os.fdopen(temp_fd, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=settings.CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)

                # Verify it's actually a PDF by checking file header
                with open(temp_path, 'rb') as f:
                    header = f.read(4)
                    if header != b'%PDF':
                        os.unlink(temp_path)
                        raise PermanentException("Downloaded file is not a valid PDF (missing PDF header)")

                # If valid, move to final destination
                shutil.move(temp_path, output_path)
                return True, None

            except (PermanentException, RetryableException):
                # Clean up temp file and re-raise
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise
            except Exception as e:
                # Clean up temp file on other errors
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

        except requests.Timeout:
            raise RetryableException("Download timeout")
        except requests.ConnectionError as e:
            raise RetryableException(f"Connection error: {e}")
        except (PermanentException, RetryableException):
            # Re-raise classified exceptions
            raise
        except Exception as e:
            # Unknown errors are considered retryable (conservative)
            raise RetryableException(f"Download error: {e}")
    
    def _download_with_curl_cffi(self, url: str, output_path: str) -> Tuple[bool, Optional[str]]:
        """
        Bypass CDN protection using curl_cffi with browser impersonation.

        This is used as a fallback when regular requests get 403 errors,
        typically from Akamai or other CDN protection systems.

        Implements per-domain rate limiting to be respectful to servers.

        Args:
            url: URL to download from
            output_path: Path to save file

        Returns:
            Tuple of (success: bool, error_msg: Optional[str])
        """
        try:
            from curl_cffi import requests as cf_requests
        except ImportError:
            return False, "curl_cffi not installed (pip install curl-cffi)"

        import tempfile
        import os
        import shutil
        from urllib.parse import urlparse

        try:
            # Extract domain for rate limiting
            domain = urlparse(url).netloc

            # Rate limiting: wait if we recently made a request to this domain
            if domain in self._last_bypass_time:
                elapsed = time.time() - self._last_bypass_time[domain]
                if elapsed < self._bypass_delay:
                    wait_time = self._bypass_delay - elapsed
                    logger.info(f"[curl_cffi] Rate limiting: waiting {wait_time:.1f}s for {domain}")
                    time.sleep(wait_time)

            # Use Chrome 110 impersonation - works well for most CDNs
            logger.debug(f"[curl_cffi] Downloading with Chrome 110 impersonation: {url}")
            response = cf_requests.get(url, impersonate='chrome110', timeout=self.timeout)

            # Update last request time for this domain
            self._last_bypass_time[domain] = time.time()

            if response.status_code != 200:
                return False, f"HTTP {response.status_code}"

            # Check content type
            content_type = response.headers.get('Content-Type', '')
            if 'html' in content_type.lower():
                return False, f"Server returned HTML (Content-Type: {content_type})"

            # Download to temporary location first
            temp_fd, temp_path = tempfile.mkstemp(suffix='.pdf')

            try:
                with os.fdopen(temp_fd, 'wb') as f:
                    f.write(response.content)

                # Verify it's actually a PDF
                with open(temp_path, 'rb') as f:
                    header = f.read(4)
                    if header != b'%PDF':
                        os.unlink(temp_path)
                        return False, "Downloaded file is not a valid PDF"

                # Move to final destination
                shutil.move(temp_path, output_path)
                logger.debug(f"[curl_cffi] Successfully downloaded {len(response.content)} bytes")
                return True, None

            except Exception as e:
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                raise

        except Exception as e:
            logger.debug(f"[curl_cffi] Download failed: {e}")
            return False, str(e)

    def get_page_content(self, url: str) -> Tuple[Optional[str], Optional[int]]:
        """
        Get HTML content from a URL with automatic curl_cffi fallback on 403.

        Returns:
            Tuple of (html_content, status_code)
        """
        try:
            response = self.session.get(url, timeout=self.timeout)

            # If we get 403, try curl_cffi bypass
            if response.status_code == 403:
                logger.warning(f"Got 403 accessing page, attempting curl_cffi bypass...")
                html, status = self._get_page_with_curl_cffi(url)
                if html:
                    logger.info("Successfully fetched page using curl_cffi bypass")
                    return html, status
                else:
                    logger.warning(f"curl_cffi bypass also failed for page access")

            return response.text, response.status_code
        except Exception as e:
            logger.error(f"Error fetching page content: {e}")
            return None, None

    def _get_page_with_curl_cffi(self, url: str) -> Tuple[Optional[str], Optional[int]]:
        """
        Fetch page content using curl_cffi with browser impersonation.

        Args:
            url: URL to fetch

        Returns:
            Tuple of (html_content, status_code)
        """
        try:
            from curl_cffi import requests as cf_requests
        except ImportError:
            return None, None

        import time
        from urllib.parse import urlparse

        try:
            # Extract domain for rate limiting
            domain = urlparse(url).netloc

            # Rate limiting: wait if we recently made a request to this domain
            if domain in self._last_bypass_time:
                elapsed = time.time() - self._last_bypass_time[domain]
                if elapsed < self._bypass_delay:
                    wait_time = self._bypass_delay - elapsed
                    logger.info(f"[curl_cffi] Rate limiting: waiting {wait_time:.1f}s for {domain}")
                    time.sleep(wait_time)

            # Use Chrome 110 impersonation
            logger.debug(f"[curl_cffi] Fetching page with Chrome 110 impersonation: {url}")
            response = cf_requests.get(url, impersonate='chrome110', timeout=self.timeout)

            # Update last request time for this domain
            self._last_bypass_time[domain] = time.time()

            logger.debug(f"[curl_cffi] Page fetch status: {response.status_code}")
            return response.text, response.status_code

        except Exception as e:
            logger.debug(f"[curl_cffi] Page fetch failed: {e}")
            return None, None