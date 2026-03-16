"""
BASE OAI-PMH source implementation.

Uses the BASE OAI-PMH interface (IP-restricted) to resolve DOIs to OA links.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

from ..core.pdf_link_extractor import derive_publisher_pdf_candidates, should_try_html_landing
from ..utils.logging import get_logger
from ..utils.retry import (
    APIRetryConfig,
    PermanentError,
    RetryableError,
    retry_with_classification,
)
from .base import PaperSource

logger = get_logger(__name__)


class BASESource(PaperSource):
    """BASE open-access source (OAI-PMH interface)."""

    _RESTRICTED_COOLDOWN_SECONDS = 3600

    _FAST_FAIL_SKIP_PDF_HOSTS = (
        "sciencedirect.com",
        "onlinelibrary.wiley.com",
        "tandfonline.com",
        "academic.oup.com",
        "downloads.hindawi.com",
        "scispace.com",
    )

    def __init__(self, timeout: int = 30, *, fast_fail: bool = False):
        self.fast_fail = fast_fail
        self.timeout = min(timeout, 5) if fast_fail else timeout
        self.base_url = "http://oai.base-search.net/oai"
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"User-Agent": "scihub-cli/1.0 (BASE OAI lookup)"})
        adapter = HTTPAdapter(pool_connections=16, pool_maxsize=16)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self._metadata_cache: dict[str, dict[str, Any] | None] = {}
        self._restricted_until: float | None = None
        self.retry_config = APIRetryConfig()
        if self.fast_fail:
            self.retry_config.max_attempts = 2
            self.retry_config.base_delay = 0.0
            self.retry_config.max_delay = 0.0

    @property
    def name(self) -> str:
        return "BASE"

    def can_handle(self, doi: str) -> bool:
        return doi.startswith("10.")

    def get_metadata(self, doi: str) -> dict[str, Any] | None:
        return self._fetch_metadata(doi)

    def get_pdf_url(self, doi: str) -> str | None:
        metadata = self._fetch_metadata(doi)
        if not metadata:
            return None
        pdf_url = metadata.get("pdf_url")
        if not pdf_url:
            logger.debug(f"[BASE] No PDF URL available for {doi}")
            return None
        if self._should_skip_pdf_url(pdf_url):
            logger.info(f"[BASE] Fast-fail skip challenge-heavy PDF URL: {pdf_url}")
            return None
        logger.info(f"[BASE] Found OA paper: {doi}")
        logger.debug(f"[BASE] PDF URL: {pdf_url}")
        return pdf_url

    def _is_restricted(self) -> bool:
        if self._restricted_until is None:
            return False
        return time.monotonic() < self._restricted_until

    def _fetch_metadata(self, doi: str) -> dict[str, Any] | None:
        if doi in self._metadata_cache:
            logger.debug(f"[BASE] Using cached metadata for {doi}")
            return self._metadata_cache[doi]

        if self._is_restricted():
            logger.info("[BASE] Skipping API due to restricted access cooldown")
            return None

        def _attempt_fetch():
            return self._fetch_from_api(doi)

        try:
            metadata = retry_with_classification(
                _attempt_fetch, self.retry_config, f"BASE OAI for {doi}"
            )
            self._metadata_cache[doi] = metadata
            return metadata
        except PermanentError:
            self._metadata_cache[doi] = None
            return None
        except Exception:
            return None

    def _fetch_from_api(self, doi: str) -> dict[str, Any] | None:
        params_primary = {
            "verb": "ListRecords",
            "metadataPrefix": "base_dc",
            "set": f'oa:1+doi:"{doi}"',
        }
        params_fallback = {
            "verb": "ListRecords",
            "metadataPrefix": "base_dc",
            "set": f'doi:"{doi}"',
        }
        for params in (params_primary, params_fallback):
            try:
                response = self.session.get(self.base_url, params=params, timeout=self.timeout)
            except requests.Timeout as e:
                raise RetryableError("Request timeout") from e
            except requests.RequestException as e:
                raise RetryableError(f"Request error: {e}") from e

            if response.status_code == 403:
                self._restricted_until = time.monotonic() + self._RESTRICTED_COOLDOWN_SECONDS
                raise PermanentError("Access denied (403)")
            if response.status_code == 429:
                raise RetryableError("Rate limited")
            if response.status_code >= 500:
                raise RetryableError(f"Server error {response.status_code}")
            if response.status_code != 200:
                raise PermanentError(f"Unexpected status {response.status_code}")

            try:
                root = ET.fromstring(response.text)
            except ET.ParseError as e:
                raise PermanentError(f"Parse error: {e}") from e

            error = root.find(".//{*}error")
            if error is not None:
                code = (error.attrib.get("code") or "").lower()
                if code == "restrictedinterface":
                    self._restricted_until = time.monotonic() + self._RESTRICTED_COOLDOWN_SECONDS
                    raise PermanentError("Restricted interface")
                if code == "norecordsmatch":
                    continue
                if code == "badargument":
                    continue
                raise PermanentError(f"OAI error: {code or 'unknown'}")

            records = root.findall(".//{*}record")
            if not records:
                continue

            for record in records:
                metadata_elem = record.find(".//{*}metadata")
                if metadata_elem is None:
                    continue

                urls = self._extract_urls_from_metadata(metadata_elem)
                if not urls:
                    continue

                pdf_url = None
                landing_candidates: list[str] = []
                for url in urls:
                    if self._looks_like_pdf_url(url):
                        pdf_url = url
                        break
                    landing_candidates.append(url)

                if not pdf_url:
                    derived = self._derive_pdf_from_landing_urls(landing_candidates)
                    if derived:
                        if self._should_skip_pdf_url(derived):
                            logger.info(
                                "[BASE] Fast-fail skip derived PDF candidate: %s",
                                derived,
                            )
                        else:
                            pdf_url = derived

                if not pdf_url:
                    for landing in landing_candidates:
                        if should_try_html_landing(landing):
                            pdf_url = landing
                            break

                if pdf_url:
                    return {
                        "title": "",
                        "year": None,
                        "journal": "",
                        "is_oa": True,
                        "pdf_url": pdf_url,
                        "source": "BASE",
                    }

            continue

        raise PermanentError("DOI not found")

    @staticmethod
    def _extract_urls_from_metadata(metadata_elem: ET.Element) -> list[str]:
        urls: list[str] = []
        for elem in metadata_elem.iter():
            tag = elem.tag.lower()
            if not tag.endswith("identifier") and not tag.endswith("link") and not tag.endswith("url"):
                continue
            text = (elem.text or "").strip()
            if text.startswith("http://") or text.startswith("https://"):
                urls.append(text)
        return urls

    def _should_skip_pdf_url(self, pdf_url: str) -> bool:
        if not self.fast_fail or not pdf_url:
            return False
        parsed = urlparse(pdf_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        host = parsed.netloc.lower()
        if not any(marker in host for marker in self._FAST_FAIL_SKIP_PDF_HOSTS):
            return False
        path = (parsed.path or "").lower()
        query = (parsed.query or "").lower()
        return path.endswith(".pdf") or ".pdf" in query or "/pdf" in path or "/pdfft" in path

    @staticmethod
    def _looks_like_pdf_url(url: str) -> bool:
        if not url:
            return False
        url_lower = url.lower()
        if url_lower.endswith(".pdf"):
            return True
        landing_patterns = [
            "/doi.org/",
            "/abstract",
            "/article/",
            "/stable/",
            "researchgate",
        ]
        if any(pattern in url_lower for pattern in landing_patterns):
            return False
        pdf_patterns = [
            "/pdf",
            "download",
            "content/pdf",
            "/article-pdf/",
            "/pdfviewer/",
            "viewer/pdf",
        ]
        return any(pattern in url_lower for pattern in pdf_patterns)

    @staticmethod
    def _derive_pdf_from_landing_url(landing_url: str | None) -> str | None:
        if not landing_url:
            return None
        candidates = derive_publisher_pdf_candidates(landing_url)
        if candidates:
            return candidates[0]
        return None

    @classmethod
    def _derive_pdf_from_landing_urls(cls, landing_urls: list[str]) -> str | None:
        for url in landing_urls:
            derived = cls._derive_pdf_from_landing_url(url)
            if derived:
                return derived
        return None
