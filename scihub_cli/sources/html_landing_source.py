"""
Generic HTML landing page source implementation.

This source tries to extract a direct PDF link from an article landing page.
It is primarily intended for open-access repository/journal pages where the PDF
URL is discoverable in the HTML (e.g. citation meta tags or download links).
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

from ..core.downloader import FileDownloader
from ..utils.logging import get_logger
from .base import PaperSource

logger = get_logger(__name__)


class HTMLLandingSource(PaperSource):
    """Extract PDF URLs from generic HTML pages."""

    _SKIP_SCHEMES = ("mailto:", "javascript:", "data:")

    def __init__(self, downloader: FileDownloader):
        self.downloader = downloader

    @property
    def name(self) -> str:
        return "HTML Landing"

    def can_handle(self, identifier: str) -> bool:
        cleaned = self._strip_fragment(identifier)
        parsed = urlparse(cleaned)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False

        # If the URL already looks like a direct PDF, let DirectPDFSource handle it first.
        return not parsed.path.lower().endswith(".pdf")

    def get_pdf_url(self, identifier: str) -> str | None:
        if not self.can_handle(identifier):
            return None

        base_url = self._strip_fragment(identifier)
        html, status = self.downloader.get_page_content(base_url)
        if not html or status != 200:
            return None

        # Sometimes a server returns a PDF even for a non-.pdf URL.
        if html.lstrip().startswith("%PDF"):
            logger.debug("[HTML Landing] Page content appears to be a PDF; using original URL")
            return base_url

        soup = BeautifulSoup(html, "html.parser")

        candidates: list[tuple[int, str]] = []

        # 1) High-signal citation meta tags
        for meta in soup.find_all("meta", attrs={"name": re.compile(r"citation_pdf_url", re.I)}):
            content = (meta.get("content") or "").strip()
            if content:
                candidates.append((1000, self._absolutize(base_url, content)))

        # 2) <link type="application/pdf" href="...">
        for link in soup.find_all("link", href=True):
            link_type = (link.get("type") or "").lower()
            href = (link.get("href") or "").strip()
            if not href:
                continue
            score = 0
            if "pdf" in link_type:
                score += 900
            score += self._score_url(href)
            if score:
                candidates.append((score, self._absolutize(base_url, href)))

        # 3) Embedded PDF viewers
        for tag_name, attr in (("iframe", "src"), ("embed", "src"), ("object", "data")):
            for tag in soup.find_all(tag_name):
                src = (tag.get(attr) or "").strip()
                if not src:
                    continue
                score = self._score_url(src) + 300
                candidates.append((score, self._absolutize(base_url, src)))

        # 4) Anchor links that look like PDF downloads
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href:
                continue

            score = self._score_url(href)
            if not score:
                continue

            text = (a.get_text(" ", strip=True) or "").lower()
            if "pdf" in text:
                score += 60
            if "download" in text or "下载" in text:
                score += 40

            candidates.append((score, self._absolutize(base_url, href)))

        best = self._pick_best_candidate(candidates)
        if best:
            logger.info(f"[HTML Landing] Extracted PDF URL: {best}")
        return best

    @classmethod
    def _score_url(cls, url: str) -> int:
        if not url:
            return 0

        url_lower = url.lower()
        if url_lower.startswith(cls._SKIP_SCHEMES):
            return 0

        score = 0
        if url_lower.endswith(".pdf"):
            score += 800
        if ".pdf?" in url_lower or ".pdf&" in url_lower:
            score += 750
        if "/pdf" in url_lower:
            score += 650
        if "pdf=render" in url_lower:
            score += 650
        if "download" in url_lower:
            score += 500
        if "wp-content/uploads" in url_lower:
            score += 500
        if "files.eric.ed.gov/fulltext" in url_lower:
            score += 500

        return score

    @staticmethod
    def _pick_best_candidate(candidates: list[tuple[int, str]]) -> str | None:
        best_score = -1
        best_url: str | None = None
        for score, url in candidates:
            if not url:
                continue
            if score > best_score:
                best_score = score
                best_url = url
        return best_url

    @classmethod
    def _absolutize(cls, base_url: str, href: str) -> str:
        href = href.strip()
        absolute = urljoin(base_url, href)
        return cls._strip_fragment(absolute)

    @staticmethod
    def _strip_fragment(url: str) -> str:
        parsed = urlparse(url)
        if not parsed.fragment:
            return url
        return urlunparse(parsed._replace(fragment=""))
