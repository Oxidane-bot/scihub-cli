"""
OpenAIRE search API source implementation.

Uses the OpenAIRE search API to resolve DOIs to OA repository links.
"""

from __future__ import annotations

import re
import time
from typing import Any, Iterable
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


class OpenAireSource(PaperSource):
    """OpenAIRE open-access source."""

    _RATE_LIMIT_COOLDOWN_SECONDS = 120

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
        self.base_url = "https://api.openaire.eu/search/researchProducts"
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"User-Agent": "scihub-cli/1.0 (OpenAIRE OA lookup)"})
        adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self._metadata_cache: dict[str, dict[str, Any] | None] = {}
        self._rate_limited_until: float | None = None
        self.retry_config = APIRetryConfig()
        if self.fast_fail:
            self.retry_config.max_attempts = 2
            self.retry_config.base_delay = 0.0
            self.retry_config.max_delay = 0.0

    @property
    def name(self) -> str:
        return "OpenAIRE"

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
            logger.debug(f"[OpenAIRE] No PDF URL available for {doi}")
            return None
        if self._should_skip_pdf_url(pdf_url):
            logger.info(f"[OpenAIRE] Fast-fail skip challenge-heavy PDF URL: {pdf_url}")
            return None
        logger.info(f"[OpenAIRE] Found OA paper: {doi}")
        logger.debug(f"[OpenAIRE] PDF URL: {pdf_url}")
        return pdf_url

    def _is_rate_limited(self) -> bool:
        if self._rate_limited_until is None:
            return False
        return time.monotonic() < self._rate_limited_until

    def _fetch_metadata(self, doi: str) -> dict[str, Any] | None:
        if doi in self._metadata_cache:
            logger.debug(f"[OpenAIRE] Using cached metadata for {doi}")
            return self._metadata_cache[doi]

        if self._is_rate_limited():
            cooldown = self._rate_limited_until - time.monotonic() if self._rate_limited_until else 0
            logger.info(
                "[OpenAIRE] Skipping API due to recent rate limit (cooldown %.0fs)",
                cooldown,
            )
            return None

        def _attempt_fetch():
            return self._fetch_from_api(doi)

        try:
            metadata = retry_with_classification(
                _attempt_fetch, self.retry_config, f"OpenAIRE API for {doi}"
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
            params = {"doi": doi, "format": "json"}
            response = self.session.get(self.base_url, params=params, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json() or {}
                results = (
                    (data.get("response") or {}).get("results") or {}
                ).get("result") or []
                if not isinstance(results, list) or not results:
                    raise PermanentError("DOI not found")

                for result in results:
                    metadata = result.get("metadata") if isinstance(result, dict) else None
                    if not isinstance(metadata, dict):
                        continue

                    open_urls, other_urls = self._extract_urls(metadata)
                    urls = open_urls or other_urls
                    if not urls:
                        continue

                    pdf_url = None
                    landing_candidates: list[str] = []
                    for url in urls:
                        if not url:
                            continue
                        if self._looks_like_pdf_url(url):
                            pdf_url = url
                            break
                        landing_candidates.append(url)

                    if not pdf_url:
                        derived = self._derive_pdf_from_landing_urls(landing_candidates)
                        if derived:
                            if self._should_skip_pdf_url(derived):
                                logger.info(
                                    "[OpenAIRE] Fast-fail skip derived PDF candidate: %s",
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
                        title = self._extract_title(metadata)
                        year = self._extract_year(metadata)
                        return {
                            "title": title or "",
                            "year": year,
                            "journal": "",
                            "is_oa": bool(open_urls),
                            "pdf_url": pdf_url,
                            "source": "OpenAIRE",
                        }

                raise PermanentError("No OA URL found")

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

    @staticmethod
    def _ensure_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    @staticmethod
    def _extract_text_values(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            if "$" in value:
                return [str(value.get("$"))]
        return []

    def _extract_instance_urls(self, instance: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for item in self._ensure_list(instance.get("url")):
            urls.extend(self._extract_text_values(item))
        for webresource in self._ensure_list(instance.get("webresource")):
            if isinstance(webresource, dict):
                urls.extend(self._extract_text_values(webresource.get("url")))
        return [url for url in urls if isinstance(url, str)]

    def _extract_accessright(self, instance: dict[str, Any]) -> str:
        access = instance.get("accessright")
        if isinstance(access, dict):
            classid = access.get("@classid") or access.get("@classname") or access.get("$")
            return str(classid or "").upper()
        if isinstance(access, str):
            return access.upper()
        return ""

    def _extract_urls(self, metadata: dict[str, Any]) -> tuple[list[str], list[str]]:
        open_urls: list[str] = []
        other_urls: list[str] = []
        entity = metadata.get("oaf:entity") or {}
        result = entity.get("oaf:result") or {}
        children = result.get("children") or {}

        instance_items: list[dict[str, Any]] = []
        for key in ("result", "instance"):
            for item in self._ensure_list(children.get(key)):
                if isinstance(item, dict):
                    instance = item.get("instance")
                    if isinstance(instance, dict):
                        instance_items.append(instance)
                    elif key == "instance":
                        instance_items.append(item)

        for instance in instance_items:
            access = self._extract_accessright(instance)
            urls = self._extract_instance_urls(instance)
            if not urls:
                continue
            if access == "OPEN":
                open_urls.extend(urls)
            else:
                other_urls.extend(urls)

        def _clean(urls: Iterable[str]) -> list[str]:
            cleaned: list[str] = []
            for url in urls:
                if not isinstance(url, str):
                    continue
                if url.startswith("http://") or url.startswith("https://"):
                    cleaned.append(url)
            return cleaned

        return _clean(open_urls), _clean(other_urls)

    @staticmethod
    def _extract_title(metadata: dict[str, Any]) -> str:
        entity = metadata.get("oaf:entity") or {}
        result = entity.get("oaf:result") or {}
        title = result.get("title")
        if isinstance(title, dict):
            return str(title.get("$") or "")
        if isinstance(title, str):
            return title
        return ""

    @staticmethod
    def _extract_year(metadata: dict[str, Any]) -> int | None:
        entity = metadata.get("oaf:entity") or {}
        result = entity.get("oaf:result") or {}
        date_value = result.get("dateofacceptance") or result.get("publicationDate")
        if isinstance(date_value, dict):
            date_value = date_value.get("$")
        if not date_value:
            return None
        match = re.search(r"(19|20)\\d{2}", str(date_value))
        if not match:
            return None
        return int(match.group(0))

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
