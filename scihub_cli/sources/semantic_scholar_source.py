"""
Semantic Scholar API source implementation.

Uses the Semantic Scholar Graph API to resolve DOIs to open-access PDF links.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote, urlparse

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


class SemanticScholarSource(PaperSource):
    """Semantic Scholar open-access source."""

    _RATE_LIMIT_COOLDOWN_SECONDS = 120

    _FAST_FAIL_SKIP_PDF_HOSTS = (
        "sciencedirect.com",
        "onlinelibrary.wiley.com",
        "tandfonline.com",
        "academic.oup.com",
        "downloads.hindawi.com",
        "scispace.com",
    )

    def __init__(
        self,
        timeout: int = 30,
        *,
        api_key: str | None = None,
        fast_fail: bool = False,
    ):
        self.fast_fail = fast_fail
        self.timeout = min(timeout, 5) if fast_fail else timeout
        self.api_key = (api_key or "").strip() or None
        self._rate_limited_until: float | None = None
        self.base_url = "https://api.semanticscholar.org/graph/v1/paper"
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(
            {"User-Agent": "scihub-cli/1.0 (Semantic Scholar OA lookup)"}
        )
        if self.api_key:
            self.session.headers.update({"x-api-key": self.api_key})
        adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self._metadata_cache: dict[str, dict[str, Any] | None] = {}
        self.retry_config = APIRetryConfig()
        if self.fast_fail:
            self.retry_config.max_attempts = 2
            self.retry_config.base_delay = 0.0
            self.retry_config.max_delay = 0.0

    @property
    def name(self) -> str:
        return "Semantic Scholar"

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
            logger.debug(f"[Semantic Scholar] No PDF URL available for {doi}")
            return None
        if self._should_skip_pdf_url(pdf_url):
            logger.info(f"[Semantic Scholar] Fast-fail skip challenge-heavy PDF URL: {pdf_url}")
            return None
        logger.info(f"[Semantic Scholar] Found OA paper: {doi}")
        logger.debug(f"[Semantic Scholar] PDF URL: {pdf_url}")
        return pdf_url

    def _is_rate_limited(self) -> bool:
        if self._rate_limited_until is None:
            return False
        return time.monotonic() < self._rate_limited_until

    def _fetch_metadata(self, doi: str) -> dict[str, Any] | None:
        if doi in self._metadata_cache:
            logger.debug(f"[Semantic Scholar] Using cached metadata for {doi}")
            return self._metadata_cache[doi]

        if self._is_rate_limited():
            cooldown = self._rate_limited_until - time.monotonic() if self._rate_limited_until else 0
            logger.info(
                "[Semantic Scholar] Skipping API due to recent rate limit (cooldown %.0fs)",
                cooldown,
            )
            return None

        def _attempt_fetch():
            return self._fetch_from_api(doi)

        try:
            metadata = retry_with_classification(
                _attempt_fetch, self.retry_config, f"Semantic Scholar API for {doi}"
            )
            self._metadata_cache[doi] = metadata
            return metadata
        except PermanentError:
            self._metadata_cache[doi] = None
            return None
        except Exception:
            return None

    def _fetch_from_api(self, doi: str) -> dict[str, Any] | None:
        try:
            paper_id = f"DOI:{doi}"
            encoded_id = quote(paper_id, safe=":")
            url = f"{self.base_url}/{encoded_id}"
            params = {
                "fields": "title,year,venue,url,isOpenAccess,openAccessPdf",
            }
            response = self.session.get(url, params=params, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json() or {}
                is_oa = bool(data.get("isOpenAccess"))
                open_pdf = data.get("openAccessPdf") or {}
                pdf_url = open_pdf.get("url")
                landing_candidates: list[str] = []

                if pdf_url and not self._looks_like_pdf_url(pdf_url):
                    landing_candidates.append(pdf_url)
                    pdf_url = None

                if not pdf_url and is_oa:
                    derived = self._derive_pdf_from_landing_urls(landing_candidates)
                    if derived:
                        if self._should_skip_pdf_url(derived):
                            logger.info(
                                "[Semantic Scholar] Fast-fail skip derived PDF candidate: %s",
                                derived,
                            )
                        else:
                            pdf_url = derived

                if not pdf_url and is_oa:
                    for landing in landing_candidates:
                        if self._should_skip_landing_url(landing):
                            continue
                        if should_try_html_landing(landing):
                            pdf_url = landing
                            break

                return {
                    "title": data.get("title") or "",
                    "year": data.get("year"),
                    "journal": data.get("venue") or "",
                    "is_oa": is_oa,
                    "pdf_url": pdf_url,
                    "source": "Semantic Scholar",
                }

            if response.status_code == 404:
                raise PermanentError("DOI not found")
            if response.status_code == 429:
                if self.fast_fail:
                    self._rate_limited_until = time.monotonic() + self._RATE_LIMIT_COOLDOWN_SECONDS
                    raise PermanentError("Rate limited")
                raise RetryableError("Rate limited")
            if response.status_code in (401, 403):
                raise PermanentError(f"Access denied ({response.status_code})")
            if response.status_code >= 500:
                raise RetryableError(f"Server error {response.status_code}")

            raise PermanentError(f"Unexpected status {response.status_code}")

        except requests.Timeout as e:
            raise RetryableError("Request timeout") from e
        except requests.RequestException as e:
            raise RetryableError(f"Request error: {e}") from e
        except (KeyError, ValueError, TypeError) as e:
            raise PermanentError(f"Parse error: {e}") from e

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
    def _should_skip_landing_url(url: str) -> bool:
        if not url:
            return True
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        return "semanticscholar.org" in host

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
            "semanticscholar.org",
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
