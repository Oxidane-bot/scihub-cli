"""
OpenAlex source implementation.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter

from ..utils.logging import get_logger
from ..utils.retry import (
    APIRetryConfig,
    PermanentError,
    RetryableError,
    retry_with_classification,
)
from ..core.pdf_link_extractor import derive_publisher_pdf_candidates, should_try_html_landing
from .base import PaperSource

logger = get_logger(__name__)


class OpenAlexSource(PaperSource):
    """OpenAlex open-access source."""

    _RATE_LIMIT_COOLDOWN_SECONDS = 120

    _FAST_FAIL_SKIP_PDF_HOSTS = (
        "sciencedirect.com",
        "onlinelibrary.wiley.com",
        "tandfonline.com",
        "academic.oup.com",
        "scispace.com",
    )

    def __init__(
        self,
        timeout: int = 30,
        *,
        email: str | None = None,
        api_key: str | None = None,
        fast_fail: bool = False,
    ):
        self.fast_fail = fast_fail
        self.timeout = min(timeout, 5) if fast_fail else timeout
        self.email = (email or "").strip() or None
        self.api_key = (api_key or "").strip() or None
        self._rate_limited_until: float | None = None
        self.base_url = "https://api.openalex.org/works"
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"User-Agent": "scihub-cli/1.0 (OpenAlex OA lookup)"})
        adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        # Metadata caching
        self._metadata_cache: dict[str, dict[str, Any] | None] = {}

        # Retry configuration for API calls
        self.retry_config = APIRetryConfig()
        if self.fast_fail:
            self.retry_config.max_attempts = 2
            self.retry_config.base_delay = 0.0
            self.retry_config.max_delay = 0.0

    @property
    def name(self) -> str:
        return "OpenAlex"

    def can_handle(self, doi: str) -> bool:
        return doi.startswith("10.")

    def get_pdf_url(self, doi: str) -> str | None:
        metadata = self._fetch_metadata(doi)
        if not metadata:
            return None
        if not metadata.get("is_oa"):
            logger.debug(f"[OpenAlex] Paper {doi} is not open access")
            return None
        pdf_url = metadata.get("pdf_url")
        if pdf_url:
            if self._should_skip_pdf_url(pdf_url):
                logger.info(f"[OpenAlex] Fast-fail skip challenge-heavy PDF URL: {pdf_url}")
                return None
            oa_status = metadata.get("oa_status", "unknown")
            logger.info(f"[OpenAlex] Found OA paper (status: {oa_status}): {doi}")
            logger.debug(f"[OpenAlex] PDF URL: {pdf_url}")
            return pdf_url
        logger.warning(f"[OpenAlex] No direct PDF URL for {doi}")
        return None

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
        return path.endswith(".pdf") or ".pdf" in query or "/pdf" in path or "pdfft" in path

    def get_metadata(self, doi: str) -> dict[str, Any] | None:
        return self._fetch_metadata(doi)

    def get_cached_metadata(self, doi: str) -> dict[str, Any] | None:
        return self._metadata_cache.get(doi)

    def _fetch_metadata(self, doi: str) -> dict[str, Any] | None:
        if doi in self._metadata_cache:
            logger.debug(f"[OpenAlex] Using cached metadata for {doi}")
            return self._metadata_cache[doi]

        if self._is_rate_limited():
            cooldown = self._rate_limited_until - time.monotonic() if self._rate_limited_until else 0
            logger.info("[OpenAlex] Skipping API due to recent rate limit (cooldown %.0fs)", cooldown)
            return None

        logger.debug(f"[OpenAlex] Fetching metadata for {doi}")

        def _attempt_fetch():
            return self._fetch_from_api(doi)

        try:
            metadata = retry_with_classification(
                _attempt_fetch, self.retry_config, f"OpenAlex API for {doi}"
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
            params = {
                "filter": f"doi:{doi}",
                "per-page": 1,
                "select": (
                    "id,doi,title,display_name,publication_year,"
                    "open_access,best_oa_location,primary_location,locations"
                ),
            }
            if self.email:
                params["mailto"] = self.email
            if self.api_key:
                params["api_key"] = self.api_key

            response = self.session.get(self.base_url, params=params, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json()
                results = data.get("results") or []
                if not isinstance(results, list) or not results:
                    raise PermanentError("DOI not found")
                work = results[0] or {}

                open_access = work.get("open_access") or {}
                is_oa = bool(open_access.get("is_oa"))
                oa_status = open_access.get("oa_status") or ""

                best_oa = work.get("best_oa_location") or {}
                landing_candidates: list[str] = []
                pdf_url = best_oa.get("pdf_url")
                if pdf_url and not self._looks_like_pdf_url(pdf_url):
                    landing_candidates.append(pdf_url)
                    pdf_url = None
                if not pdf_url:
                    oa_url = open_access.get("oa_url")
                    if oa_url:
                        if self._looks_like_pdf_url(oa_url):
                            pdf_url = oa_url
                        else:
                            landing_candidates.append(oa_url)

                if not pdf_url:
                    locations = work.get("locations") or []
                    if isinstance(locations, list):
                        for loc in locations:
                            if not isinstance(loc, dict):
                                continue
                            candidate = loc.get("pdf_url")
                            if candidate and self._looks_like_pdf_url(candidate):
                                pdf_url = candidate
                                break
                            landing = loc.get("landing_page_url")
                            if landing:
                                if self._looks_like_pdf_url(landing):
                                    pdf_url = landing
                                    break
                                landing_candidates.append(landing)

                primary_location = work.get("primary_location") or {}
                source = primary_location.get("source") or {}
                year = work.get("publication_year")
                if not pdf_url and is_oa:
                    for landing in (
                        best_oa.get("landing_page_url"),
                        best_oa.get("url"),
                        primary_location.get("landing_page_url"),
                    ):
                        if landing:
                            landing_candidates.append(landing)
                    if isinstance(locations, list):
                        for loc in locations:
                            if not isinstance(loc, dict):
                                continue
                            landing = loc.get("landing_page_url")
                            if landing:
                                landing_candidates.append(landing)
                    derived = self._derive_pdf_from_landing_urls(landing_candidates)
                    if derived:
                        if self._should_skip_pdf_url(derived):
                            logger.info(
                                f"[OpenAlex] Fast-fail skip derived PDF candidate: {derived}"
                            )
                        else:
                            pdf_url = derived
                if not pdf_url and is_oa:
                    for landing in landing_candidates:
                        if should_try_html_landing(landing):
                            pdf_url = landing
                            break
                return {
                    "title": work.get("title") or work.get("display_name") or "",
                    "year": int(year) if year else None,
                    "journal": source.get("display_name", ""),
                    "is_oa": is_oa,
                    "oa_status": oa_status,
                    "pdf_url": pdf_url,
                    "openalex_id": work.get("id"),
                    "source": "OpenAlex",
                }

            if response.status_code == 404:
                logger.debug(f"[OpenAlex] DOI not found: {doi}")
                raise PermanentError("DOI not found")

            if response.status_code == 429:
                logger.warning(f"[OpenAlex] Rate limited for {doi}")
                if self.fast_fail:
                    self._rate_limited_until = time.monotonic() + self._RATE_LIMIT_COOLDOWN_SECONDS
                    raise PermanentError("Rate limited")
                raise RetryableError("Rate limited")

            if response.status_code == 401 or response.status_code == 403:
                logger.warning(f"[OpenAlex] Access denied ({response.status_code}) for {doi}")
                raise PermanentError(f"Access denied ({response.status_code})")

            if response.status_code >= 500:
                logger.warning(f"[OpenAlex] Server error {response.status_code} for {doi}")
                raise RetryableError(f"Server error {response.status_code}")

            logger.warning(f"[OpenAlex] API returned {response.status_code} for {doi}")
            raise PermanentError(f"Unexpected status {response.status_code}")

        except requests.Timeout as e:
            logger.warning(f"[OpenAlex] Request timeout for {doi}")
            raise RetryableError("Request timeout") from e
        except requests.RequestException as e:
            logger.warning(f"[OpenAlex] Request error for {doi}: {e}")
            raise RetryableError(f"Request error: {e}") from e
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"[OpenAlex] Error parsing response for {doi}: {e}")
            raise PermanentError(f"Parse error: {e}") from e

    @staticmethod
    def _looks_like_pdf_url(url: str) -> bool:
        if not url:
            return False
        lowered = url.lower()
        if lowered.endswith(".pdf"):
            return True
        return any(
            token in lowered
            for token in ("/pdf", "/download/", "blobtype=pdf", "content/pdf", "/article-pdf/")
        )

    @staticmethod
    def _derive_pdf_from_landing_url(landing_url: str | None) -> str | None:
        if not landing_url:
            return None
        candidates = derive_publisher_pdf_candidates(landing_url)
        if not candidates:
            return None
        return candidates[0]

    @classmethod
    def _derive_pdf_from_landing_urls(cls, landing_urls: list[str]) -> str | None:
        seen: set[str] = set()
        for url in landing_urls:
            if not url:
                continue
            cleaned = url.strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            derived = cls._derive_pdf_from_landing_url(cleaned)
            if derived:
                return derived
        return None

    def _is_rate_limited(self) -> bool:
        if not self.fast_fail:
            return False
        if self._rate_limited_until is None:
            return False
        return time.monotonic() < self._rate_limited_until
