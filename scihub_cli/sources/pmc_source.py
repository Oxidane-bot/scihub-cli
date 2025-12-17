"""
PubMed Central (PMC) source implementation.

PMC article pages are typically HTML and require extracting the actual PDF link.
This source supports common PMC URL variants and returns a direct PDF URL.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from ..core.downloader import FileDownloader
from ..utils.logging import get_logger
from .base import PaperSource

logger = get_logger(__name__)


class PMCSource(PaperSource):
    """Download source for PubMed Central (PMC) articles."""

    _PMC_ID_RE = re.compile(r"(PMC\d+)", re.IGNORECASE)

    def __init__(self, downloader: FileDownloader):
        self.downloader = downloader

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
        html, status = self.downloader.get_page_content(article_url)
        if html and status == 200:
            pdf_url = self._extract_pdf_url_from_html(html, article_url, pmc_id)
            if pdf_url:
                logger.info(f"[PMC] Found PDF for {pmc_id}")
                return pdf_url

        # Fallback to predictable endpoints when HTML extraction fails.
        for candidate in self._fallback_pdf_urls(pmc_id):
            logger.debug(f"[PMC] Falling back to constructed PDF URL for {pmc_id}: {candidate}")
            return candidate

        return None

    @classmethod
    def _extract_pmc_id(cls, identifier: str) -> str | None:
        match = cls._PMC_ID_RE.search(identifier or "")
        if not match:
            return None
        return match.group(1).upper()

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

    @staticmethod
    def _fallback_pdf_urls(pmc_id: str) -> list[str]:
        return [
            f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/pdf/",
            f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/pdf/",
            f"https://europepmc.org/articles/{pmc_id}?pdf=render",
        ]
