"""
CORE API integration for open access paper downloads.

CORE aggregates over 32.8 million full-text open access articles from
thousands of repositories and journals worldwide.
"""

import threading
import time
from html import unescape
from typing import Optional
from urllib.parse import urlparse

import requests

from ..utils.logging import get_logger
from ..utils.retry import RetryConfig
from .base import PaperSource

logger = get_logger(__name__)


class CORESource(PaperSource):
    """
    CORE API client for finding and downloading open access papers.

    API Documentation: https://core.ac.uk/documentation/api
    """

    def __init__(self, api_key: Optional[str] = None, timeout: int = 30):
        """
        Initialize CORE API client.

        Args:
            api_key: CORE API key (optional, but recommended for better rate limits)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.timeout = timeout
        self.base_url = "https://api.core.ac.uk/v3"

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "scihub-cli/1.0 (academic research tool)"})

        if api_key:
            self.session.headers.update({"Authorization": f"Bearer {api_key}"})

        # Metadata cache to avoid duplicate API calls
        self._metadata_cache = {}

        # Retry configuration
        self.retry_config = RetryConfig(max_attempts=2, base_delay=2.0)
        # Serialize API traffic to reduce 429s under parallel downloads.
        self._api_lock = threading.Lock()
        self._next_request_time = 0.0
        self._min_request_interval = 1.0 if api_key else 10.0

    @property
    def name(self) -> str:
        return "CORE"

    def can_handle(self, doi: str) -> bool:
        """CORE searches by DOI and only returns OA content."""
        return doi.startswith("10.")

    def get_metadata(self, doi: str) -> Optional[dict]:
        """
        Get metadata for a paper by DOI.

        Args:
            doi: DOI of the paper

        Returns:
            Metadata dict or None if not found
        """
        # Check cache first
        if doi in self._metadata_cache:
            logger.debug(f"[CORE] Using cached metadata for {doi}")
            return self._metadata_cache[doi]

        logger.debug(f"[CORE] Fetching metadata for {doi}")

        try:
            metadata = self._fetch_from_api(doi)
            if metadata:
                # Cache the result
                self._metadata_cache[doi] = metadata
                return metadata
            return None
        except Exception as e:
            logger.error(f"[CORE] Failed to fetch metadata for {doi}: {e}")
            return None

    def _fetch_from_api(self, doi: str) -> Optional[dict]:
        """
        Fetch metadata from CORE API with retry logic.

        Args:
            doi: DOI to search for

        Returns:
            Metadata dict or None
        """
        # Search by DOI
        search_url = f"{self.base_url}/search/works"
        params = {"q": f'doi:"{doi}"', "limit": 1}

        for attempt in range(self.retry_config.max_attempts):
            try:
                self._wait_for_api_slot()
                response = self.session.get(search_url, params=params, timeout=self.timeout)

                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])

                    if not results:
                        logger.debug(f"[CORE] No results found for {doi}")
                        return None

                    work = results[0]

                    # Check if full text is available
                    has_fulltext = work.get("fullText") or work.get("downloadUrl")

                    if not has_fulltext:
                        logger.debug(f"[CORE] No full text available for {doi}")
                        return None

                    best_pdf_url = self._select_best_pdf_url(work)
                    links_download_urls = []
                    links = work.get("links")
                    if isinstance(links, list):
                        for item in links:
                            if not isinstance(item, dict):
                                continue
                            if item.get("type") != "download":
                                continue
                            url = item.get("url")
                            if isinstance(url, str):
                                normalized = self._normalize_candidate_url(url)
                                if normalized:
                                    links_download_urls.append(normalized)

                    return {
                        "title": work.get("title", ""),
                        "year": work.get("yearPublished"),
                        "is_oa": True,  # CORE only has OA content
                        "pdf_url": best_pdf_url,
                        "core_download_url": work.get("downloadUrl"),
                        "source_fulltext_urls": work.get("sourceFulltextUrls") or [],
                        "links_download_urls": self._dedupe_preserve_order(links_download_urls),
                        "core_id": work.get("id"),
                        "source": "CORE",
                    }

                elif response.status_code == 429:
                    # Rate limit exceeded
                    retry_after = int(response.headers.get("Retry-After", 10))
                    logger.warning(f"[CORE] Rate limit exceeded, waiting {retry_after}s")
                    self._push_next_request_window(retry_after)
                    if attempt < self.retry_config.max_attempts - 1:
                        time.sleep(retry_after)
                        continue
                    return None

                elif response.status_code == 404:
                    logger.debug(f"[CORE] Paper not found: {doi}")
                    return None

                else:
                    logger.warning(f"[CORE] API returned {response.status_code}")
                    return None

            except requests.Timeout:
                logger.warning(f"[CORE] Request timeout (attempt {attempt + 1})")
                if attempt < self.retry_config.max_attempts - 1:
                    time.sleep(self.retry_config.base_delay * (attempt + 1))
                    continue
                return None

            except requests.RequestException as e:
                logger.error(f"[CORE] Request error: {e}")
                return None

        return None

    def _wait_for_api_slot(self) -> None:
        """Throttle CORE API calls across threads to reduce rate limiting."""
        wait_for = 0.0
        with self._api_lock:
            now = time.time()
            if now < self._next_request_time:
                wait_for = self._next_request_time - now
            scheduled = max(now, self._next_request_time) + self._min_request_interval
            self._next_request_time = scheduled

        if wait_for > 0:
            time.sleep(wait_for)

    def _push_next_request_window(self, seconds: int) -> None:
        with self._api_lock:
            self._next_request_time = max(self._next_request_time, time.time() + max(seconds, 1))

    def get_pdf_url(self, doi: str) -> Optional[str]:
        """
        Get PDF download URL for a paper.

        Args:
            doi: DOI of the paper

        Returns:
            PDF URL or None if not available
        """
        metadata = self.get_metadata(doi)

        if not metadata:
            logger.debug(f"[CORE] No metadata found for {doi}")
            return None

        pdf_url = metadata.get("pdf_url")

        if pdf_url:
            logger.info(f"[CORE] Found PDF for {doi}")
            logger.debug(f"[CORE] PDF URL: {pdf_url}")
            return pdf_url
        else:
            logger.debug(f"[CORE] No PDF URL available for {doi}")
            return None

    def get_pdf_url_with_metadata(self, doi: str) -> tuple[Optional[str], Optional[dict]]:
        """
        Get both PDF URL and metadata in one call.

        Args:
            doi: DOI of the paper

        Returns:
            Tuple of (pdf_url, metadata)
        """
        metadata = self.get_metadata(doi)

        if not metadata:
            return None, None

        pdf_url = metadata.get("pdf_url")
        return pdf_url, metadata

    def _select_best_pdf_url(self, work: dict) -> Optional[str]:
        """
        Select the most reliable direct PDF URL from CORE work metadata.

        Prefer source repository full-text URLs over CORE download proxy URLs,
        because proxy URLs are more likely to be blocked by anti-bot protections.
        """
        candidates: list[str] = []

        source_urls = work.get("sourceFulltextUrls")
        if isinstance(source_urls, list):
            candidates.extend(
                self._normalize_candidate_url(str(url)) for url in source_urls if isinstance(url, str)
            )

        download_url = work.get("downloadUrl")
        if isinstance(download_url, str):
            candidates.append(self._normalize_candidate_url(download_url))

        links = work.get("links")
        if isinstance(links, list):
            for item in links:
                if not isinstance(item, dict):
                    continue
                if item.get("type") != "download":
                    continue
                link_url = item.get("url")
                if isinstance(link_url, str):
                    candidates.append(self._normalize_candidate_url(link_url))

        scored = sorted(
            ((self._score_pdf_candidate(url), url) for url in self._dedupe_preserve_order(candidates)),
            key=lambda x: x[0],
            reverse=True,
        )

        # Prefer candidates that can be probed as likely-PDF endpoints.
        for score, candidate in scored:
            if score <= 0:
                continue
            if self._probe_candidate_pdf(candidate):
                logger.debug(f"[CORE] Selected probed PDF candidate (score={score}): {candidate}")
                return candidate

        # Fallback: use scoring only when probe cannot confirm any candidate.
        for score, candidate in scored:
            if score <= 0:
                continue
            logger.debug(f"[CORE] Selected candidate URL (score={score}): {candidate}")
            return candidate

        return None

    @staticmethod
    def _dedupe_preserve_order(items: list[str]) -> list[str]:
        seen = set()
        out: list[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            out.append(item)
        return out

    @staticmethod
    def _normalize_candidate_url(url: str) -> str:
        return unescape((url or "").strip())

    def _score_pdf_candidate(self, url: str) -> int:
        if not url:
            return 0

        cleaned = url.strip()
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return 0

        url_lower = cleaned.lower()
        score = 0

        # Strong signal: looks like a direct PDF file.
        if self._looks_like_direct_pdf(url_lower):
            score += 100

        # Prefer source repository URLs over CORE proxy links.
        host = parsed.netloc.lower()
        if "core.ac.uk" not in host:
            score += 40
        else:
            score -= 10

        if parsed.scheme == "https":
            score += 10
        else:
            score -= 10

        # De-prioritize known landing-page patterns.
        landing_markers = (
            "doi.org/",
            "/abstract",
            "/article/",
            "/toc/",
            "/reader/",
            "doaj.org/toc",
        )
        if any(marker in url_lower for marker in landing_markers):
            score -= 100

        return score

    @staticmethod
    def _looks_like_direct_pdf(url_lower: str) -> bool:
        if url_lower.endswith(".pdf"):
            return True
        if ".pdf?" in url_lower or ".pdf&" in url_lower:
            return True
        if "/pdf/" in url_lower:
            return True
        return "viewcontent.cgi" in url_lower and "article=" in url_lower

    def _probe_candidate_pdf(self, url: str) -> bool:
        """
        Probe whether candidate URL looks like a real PDF endpoint.

        This avoids selecting dead or landing-page links from sourceFulltextUrls.
        """
        response = None
        try:
            response = self.session.get(
                url,
                timeout=self.timeout,
                stream=True,
                allow_redirects=True,
            )
            if response.status_code == 403:
                # May still be valid and recoverable via downloader bypass.
                return True
            if response.status_code != 200:
                return False

            content_type = (response.headers.get("Content-Type") or "").lower()
            if "html" in content_type:
                return False
            if "pdf" in content_type:
                return True

            header = b""
            for chunk in response.iter_content(chunk_size=4):
                header += chunk
                if len(header) >= 4:
                    break
            return header[:4] == b"%PDF"
        except Exception as e:
            logger.debug(f"[CORE] Candidate probe failed for {url}: {e}")
            return False
        finally:
            if response is not None:
                close = getattr(response, "close", None)
                if callable(close):
                    close()
