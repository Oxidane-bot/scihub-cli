"""
Europe PMC (OA) source implementation.

Uses the Europe PMC REST search API to resolve DOIs to open-access full text
links (core result type includes full text links).
"""

from __future__ import annotations

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
from .base import PaperSource

logger = get_logger(__name__)


class EuropePMCSource(PaperSource):
    """Europe PMC open-access source."""

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
        self.base_url = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"User-Agent": "scihub-cli/1.0 (Europe PMC OA lookup)"})
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
        return "Europe PMC"

    def can_handle(self, doi: str) -> bool:
        return doi.startswith("10.")

    def get_pdf_url(self, doi: str) -> str | None:
        metadata = self._fetch_metadata(doi)
        if not metadata:
            return None
        if not metadata.get("is_oa") and not metadata.get("has_pdf"):
            logger.debug(f"[Europe PMC] Paper {doi} is not open access")
            return None
        pdf_url = metadata.get("pdf_url")
        if pdf_url:
            if self._should_skip_pdf_url(pdf_url):
                logger.info(f"[Europe PMC] Fast-fail skip challenge-heavy PDF URL: {pdf_url}")
                return None
            logger.info(f"[Europe PMC] Found OA paper: {doi}")
            logger.debug(f"[Europe PMC] PDF URL: {pdf_url}")
            return pdf_url
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

    def _fetch_metadata(self, doi: str) -> dict[str, Any] | None:
        if doi in self._metadata_cache:
            return self._metadata_cache[doi]

        def _attempt_fetch():
            return self._fetch_from_api(doi)

        try:
            metadata = retry_with_classification(
                _attempt_fetch, self.retry_config, f"Europe PMC API for {doi}"
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
                "query": f'DOI:"{doi}"',
                "format": "json",
                "resultType": "core",
                "pageSize": 1,
            }
            response = self.session.get(self.base_url, params=params, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json()
                results = (data.get("resultList") or {}).get("result") or []
                if not isinstance(results, list) or not results:
                    raise PermanentError("DOI not found")

                record = results[0] or {}
                title = record.get("title") or ""
                year = record.get("pubYear")
                journal = record.get("journalTitle") or ""
                is_oa = self._to_bool(record.get("isOpenAccess"))
                has_pdf = self._to_bool(record.get("hasPDF")) or self._to_bool(record.get("hasPdf"))
                pmcid = self._normalize_pmcid(record.get("pmcid") or record.get("pmcId"))

                pdf_url = self._extract_pdf_url(record)
                if not pdf_url and pmcid:
                    pdf_url = self._pmcid_pdf_url(pmcid)

                return {
                    "title": title,
                    "year": int(year) if isinstance(year, str) and year.isdigit() else year,
                    "journal": journal,
                    "is_oa": is_oa,
                    "has_pdf": has_pdf,
                    "pmcid": pmcid,
                    "pdf_url": pdf_url,
                    "source": "Europe PMC",
                }

            if response.status_code == 404:
                raise PermanentError("DOI not found")
            if response.status_code == 429:
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
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"y", "yes", "true", "1"}
        if isinstance(value, int):
            return value != 0
        return False

    @staticmethod
    def _normalize_pmcid(value: Any) -> str | None:
        if not value:
            return None
        text = str(value).strip()
        if not text:
            return None
        if text.upper().startswith("PMC"):
            return text.upper()
        return f"PMC{text}"

    @staticmethod
    def _pmcid_pdf_url(pmcid: str) -> str:
        return f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmcid}&blobtype=pdf"

    def _extract_pdf_url(self, record: dict[str, Any]) -> str | None:
        fulltext = (record.get("fullTextUrlList") or {}).get("fullTextUrl") or []
        if not isinstance(fulltext, list):
            return None
        candidates: list[str] = []
        for entry in fulltext:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url") or entry.get("link")
            if not isinstance(url, str) or not url.strip():
                continue
            url = url.strip()
            doc_style = (entry.get("documentStyle") or "").lower()
            if doc_style == "pdf" or url.lower().endswith(".pdf") or "pdf" in url.lower():
                candidates.append(url)
        if candidates:
            return candidates[0]
        return None
