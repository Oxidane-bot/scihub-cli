"""
PubMed Central (PMC) source implementation.

PMC article pages are typically HTML and require extracting the actual PDF link.
This source supports common PMC URL variants and returns a direct PDF URL.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from ..core.doi_processor import DOIProcessor
from ..core.downloader import FileDownloader
from ..utils.logging import get_logger
from ..utils.retry import DEFAULT_MAX_RETRY_AFTER_SECONDS, parse_retry_after
from .base import PaperSource
from .europe_pmc_common import EuropePMCHostThrottle

logger = get_logger(__name__)


class PMCSource(PaperSource):
    """Download source for PubMed Central (PMC) articles."""

    _PAGE_RETRY_ATTEMPTS = 2
    _PAGE_RETRY_BACKOFF_SECONDS = 1.0

    def __init__(self, downloader: FileDownloader):
        self.downloader = downloader
        self._metadata_cache: dict[str, dict[str, str] | None] = {}

    @property
    def name(self) -> str:
        return "PMC"

    def can_handle(self, identifier: str) -> bool:
        return self._extract_pmc_id(identifier) is not None

    def get_pdf_url(self, identifier: str) -> str | None:
        pmc_id = self._extract_pmc_id(identifier)
        if not pmc_id:
            return None

        # If the user already provides a direct PDF endpoint, just use it.
        cleaned = self._strip_fragment(identifier)
        if self._looks_like_pmc_pdf_url(cleaned):
            logger.debug(f"[PMC] Using provided PDF-like URL for {pmc_id}: {cleaned}")
            return cleaned

        article_url = self._normalize_article_url(cleaned, pmc_id)
        html, status = self._get_article_page(article_url)
        if html and status == 200:
            pdf_url = self._extract_pdf_url_from_html(html, article_url, pmc_id)
            metadata = self._extract_metadata_from_html(html)
            if metadata:
                self._metadata_cache[pmc_id] = metadata
            if pdf_url:
                logger.info(f"[PMC] Found PDF for {pmc_id}")
                return pdf_url

        if status == 429:
            # Do not turn a rate-limit response into host rotation.  The
            # bounded retry above already honored Retry-After; callers can
            # continue through their normal source chain later.
            logger.info("[PMC] Rate limit persisted for %s; skipping fallback probes", pmc_id)
            return None

        # Fallback to predictable endpoints when HTML extraction fails.
        probe = getattr(self.downloader, "probe_pdf_url", None)
        for candidate in self._fallback_pdf_urls(pmc_id):
            logger.debug(f"[PMC] Falling back to constructed PDF URL for {pmc_id}: {candidate}")
            if callable(probe) and not probe(candidate):
                status_getter = getattr(self.downloader, "get_last_probe_response_status", None)
                probe_status = status_getter() if callable(status_getter) else None
                if probe_status == 429:
                    logger.info(
                        "[PMC] Rate limit persisted for %s; stopping fallback probes", pmc_id
                    )
                    return None
                logger.debug(f"[PMC] Fallback URL did not validate as PDF: {candidate}")
                continue
            return candidate

        return None

    def _get_article_page(self, article_url: str) -> tuple[str | None, int | None]:
        """Fetch a PMC page with Retry-After-aware, host-throttled retries."""

        for attempt in range(self._PAGE_RETRY_ATTEMPTS):
            EuropePMCHostThrottle.wait_for_slot(article_url)
            html, status = self.downloader.get_page_content(article_url)
            if status != 429:
                return html, status

            headers_getter = getattr(self.downloader, "get_last_page_response_headers", None)
            headers = headers_getter() if callable(headers_getter) else {}
            retry_after = parse_retry_after((headers or {}).get("Retry-After"))
            delay = retry_after if retry_after is not None else self._PAGE_RETRY_BACKOFF_SECONDS
            if delay > DEFAULT_MAX_RETRY_AFTER_SECONDS:
                # Capping this delay would retry before the provider's
                # explicit lower bound.  Stop the bounded page retry instead
                # of blocking the whole CLI on an unreasonable hint.
                logger.warning(
                    "[PMC] Retry-After %.1fs exceeds the %.1fs retry budget; stopping page retries",
                    delay,
                    DEFAULT_MAX_RETRY_AFTER_SECONDS,
                )
                return html, status
            # A 429 is a provider instruction, not a signal to rotate through
            # alternate hosts.  Hold this host and retry the same page only.
            EuropePMCHostThrottle.defer(article_url, delay)
            if attempt >= self._PAGE_RETRY_ATTEMPTS - 1:
                return html, status
            logger.info("[PMC] Rate limited; retrying page after %.1fs", delay)
            time.sleep(delay)

        return None, None

    def get_metadata(self, identifier: str) -> dict[str, str] | None:
        pmc_id = self._extract_pmc_id(identifier)
        if not pmc_id:
            return None
        return self._metadata_cache.get(pmc_id)

    @classmethod
    def _extract_pmc_id(cls, identifier: str) -> str | None:
        # Keep source routing aligned with the identity classifier.  A loose
        # regex here would make a DOI suffix or arbitrary URL query look like
        # a PMC article even though DOIProcessor correctly rejected it.
        return DOIProcessor.extract_pmc_id(identifier)

    @staticmethod
    def _strip_fragment(url: str) -> str:
        parsed = urlparse(url)
        if not parsed.fragment:
            return url
        return urlunparse(parsed._replace(fragment=""))

    @staticmethod
    def _looks_like_pmc_pdf_url(url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False

        path_lower = (parsed.path or "").lower()
        query_lower = (parsed.query or "").lower()

        if path_lower.endswith(".pdf"):
            return True
        if "/pdf/" in path_lower:
            return True
        return "pdf=render" in query_lower

    @staticmethod
    def _normalize_article_url(url: str, pmc_id: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/"

        # Prefer the modern PMC host when possible.
        netloc = parsed.netloc.lower()
        if "ncbi.nlm.nih.gov" in netloc and "pmc.ncbi.nlm.nih.gov" not in netloc:
            return f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/"

        # Ensure it ends with a trailing slash (more stable for urljoin later).
        base = urlunparse(parsed._replace(query="", fragment=""))
        return base if base.endswith("/") else f"{base}/"

    @staticmethod
    def _extract_pdf_url_from_html(html: str, base_url: str, pmc_id: str) -> str | None:
        soup = BeautifulSoup(html, "html.parser")

        # High-signal: citation_pdf_url meta tag
        meta = soup.find("meta", attrs={"name": re.compile(r"citation_pdf_url", re.I)})
        if meta and meta.get("content"):
            return meta["content"].strip()

        # Common PMC markup: link contains /pdf/ and PMC id
        link_candidates: list[str] = []
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            href_lower = href.lower()
            if "/pdf/" in href_lower or href_lower.endswith(".pdf"):
                link_candidates.append(href)

        # Prefer links that include the PMC id
        for href in link_candidates:
            absolute = urljoin(base_url, href)
            absolute_lower = absolute.lower()
            if pmc_id.lower() in absolute_lower and "/pdf" in absolute_lower:
                return absolute

        if link_candidates:
            return urljoin(base_url, link_candidates[0])

        return None

    @classmethod
    def _extract_metadata_from_html(cls, html: str) -> dict[str, str] | None:
        soup = BeautifulSoup(html, "html.parser")
        doi = None

        meta = soup.find("meta", attrs={"name": re.compile(r"citation_doi", re.I)})
        if meta and meta.get("content"):
            doi = meta["content"].strip()

        if not doi:
            meta = soup.find("meta", attrs={"name": re.compile(r"dc.identifier", re.I)})
            if meta and meta.get("content"):
                content = meta["content"].strip()
                if content.lower().startswith("doi:"):
                    doi = content.split(":", 1)[1].strip()

        if not doi:
            match = re.search(r"\b10\.\d{4,9}/[-._;()/:A-Za-z0-9]+\b", html)
            if match:
                doi = match.group(0)

        if doi:
            return {"doi": doi}
        return None

    @staticmethod
    def _fallback_pdf_urls(pmc_id: str) -> list[str]:
        return [
            f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/pdf/",
            f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/pdf/",
            f"https://europepmc.org/articles/{pmc_id}?pdf=render",
        ]
