"""
Extract and rank PDF download candidates from HTML.

Shared by:
- HTML landing page source (source-discovery phase)
- Downloader HTML recovery (download phase)
"""

from __future__ import annotations

import json
import re
from html import unescape
from typing import Any
from urllib.parse import urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup

_SKIP_SCHEMES = ("mailto:", "javascript:", "data:", "tel:")

# Conservative regexes for extracting URL-like substrings from raw HTML.
_RAW_URL_PATTERNS = (
    re.compile(r"https?://[^\s\"'<>]+", re.I),
    re.compile(r"(?<![\w/])(?:/[^\s\"'<>]+\.pdf(?:\?[^\s\"'<>]*)?)", re.I),
    re.compile(r"(?<![\w/])(?:/download/[^\s\"'<>]+)", re.I),
    re.compile(
        r"(?<![\w/])(?:/server/api/core/bitstreams/[^\s\"'<>]+/content(?:\?[^\s\"'<>]*)?)", re.I
    ),
)

_CLOUDFLARE_PATH_PATTERN = re.compile(r'(?:cUPMDTk|fa)\s*:\s*"([^"]+)"', re.I)
_SCRIPT_PDF_URL_PATTERN = re.compile(
    r"""(?:
            ["'](?:pdfUrl|pdf_url|fullTextPdfUrl|full_text_pdf_url|downloadUrl|download_url)["']\s*:\s*["']([^"']+)["']
        )
    """,
    re.I | re.X,
)

_TRACKER_HOST_MARKERS = (
    "googletagmanager.com",
    "google-analytics.com",
    "doubleclick.net",
    "googlesyndication.com",
    "facebook.com",
    "connect.facebook.net",
    "instagram.com",
    "twitter.com",
    "x.com",
    "tiktok.com",
    "hotjar.com",
    "segment.com",
)
_NON_PDF_ASSET_EXTENSIONS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".css",
    ".js",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".mp4",
    ".mp3",
    ".webm",
    ".m3u8",
    ".ts",
    ".zip",
)

_SCIENCEDIRECT_PII_PATH = re.compile(
    r"/science/article(?:/abs)?/pii/([A-Z0-9]+)",
    re.I,
)
_SCIENCEDIRECT_PII_TOKEN = re.compile(r"""["']pii["']\s*:\s*["']([A-Z0-9]+)["']""", re.I)
_TANDFONLINE_DOI_PATH = re.compile(r"/doi/(?:abs|full)/(.+)", re.I)
_NATURE_ARTICLE_PATH = re.compile(r"/articles/([^/?#]+)", re.I)


def extract_ranked_pdf_candidates(html: str, base_url: str) -> list[tuple[int, str]]:
    """
    Extract and rank possible PDF URLs from HTML.

    Returns:
        List of (score, url) sorted by score descending.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    html_unescaped = unescape(html)
    scored: dict[str, int] = {}
    order: dict[str, int] = {}
    order_counter = 0

    def _add(url: str, score: int) -> None:
        nonlocal order_counter
        if score <= 0:
            return
        cleaned = _normalize_candidate(base_url, url)
        if not cleaned:
            return
        if cleaned not in order:
            order[cleaned] = order_counter
            order_counter += 1
        if score > scored.get(cleaned, -1):
            scored[cleaned] = score

    # 1) High-signal citation meta tags
    for meta in soup.find_all("meta", attrs={"name": re.compile(r"citation_pdf_url", re.I)}):
        content = (meta.get("content") or "").strip()
        if content:
            _add(content, 1200)

    # 2) <link type="application/pdf">
    for link in soup.find_all("link", href=True):
        href = (link.get("href") or "").strip()
        if not href:
            continue
        score = _score_url(href)
        link_type = (link.get("type") or "").lower()
        if "pdf" in link_type:
            score += 900
        _add(href, score)

    # 3) Embedded viewers
    for tag_name, attr in (("iframe", "src"), ("embed", "src"), ("object", "data")):
        for tag in soup.find_all(tag_name):
            src = (tag.get(attr) or "").strip()
            if not src:
                continue
            _add(src, _score_url(src) + 300)

    # 4) Anchor links
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        score = _score_url(href)
        if score <= 0:
            continue
        text = (a.get_text(" ", strip=True) or "").lower()
        if "pdf" in text:
            score += 80
        if "download" in text or "下载" in text:
            score += 40
        _add(href, score)

    # 5) Raw URL-like tokens in HTML source
    for raw_blob in (html, html_unescaped):
        for pattern in _RAW_URL_PATTERNS:
            for match in pattern.findall(raw_blob):
                token = match[0] if isinstance(match, tuple) else match
                _add(token, _score_url(token))

    # 5.5) URL-like values hidden in inline script assignments
    for raw_blob in (html, html_unescaped):
        for token in _SCRIPT_PDF_URL_PATTERN.findall(raw_blob):
            _add(token, _score_url(token) + 120)

    # 6) Cloudflare challenge paths (often escaped)
    for token in _extract_cloudflare_tokens(html):
        _add(token, _score_url(token) + 250)

    # 7) DSpace angular state JSON payload
    for token in _extract_dspace_candidates(soup):
        _add(token, _score_url(token))

    # 8) Drupal settings JSON payload
    for token, score in _extract_drupal_candidates(soup):
        _add(token, score)

    # 9) Publisher-specific URL derivations from known article URL patterns
    for token, score in _extract_publisher_candidates(base_url, html_unescaped):
        _add(token, score)

    ranked = sorted(
        ((score, url) for url, score in scored.items()),
        key=lambda item: (-item[0], order[item[1]]),
    )
    return ranked


def extract_pdf_candidates(html: str, base_url: str, *, min_score: int = 1) -> list[str]:
    """Extract PDF-like candidates from HTML and return URLs only."""
    return [
        url for score, url in extract_ranked_pdf_candidates(html, base_url) if score >= min_score
    ]


def derive_publisher_pdf_candidates(base_url: str, html: str | None = None) -> list[str]:
    """
    Derive direct PDF candidates from known publisher URL patterns.

    This is useful as a prefetch strategy before fetching/parsing full HTML pages.
    """
    html_unescaped = unescape(html or "")
    return [url for url, _score in _extract_publisher_candidates(base_url, html_unescaped)]


def _score_url(url: str) -> int:
    if not url:
        return 0

    url_lower = url.lower()
    if url_lower.startswith(_SKIP_SCHEMES):
        return 0

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if any(marker in host for marker in _TRACKER_HOST_MARKERS):
        return 0
    path_lower = parsed.path.lower()
    if any(path_lower.endswith(ext) for ext in _NON_PDF_ASSET_EXTENSIONS):
        return 0

    score = 0
    if url_lower.endswith(".pdf"):
        score += 900
    if ".pdf?" in url_lower or ".pdf&" in url_lower:
        score += 850
    if "/pdf/" in url_lower or "/pdf?" in url_lower:
        score += 650
    if "pdf=render" in url_lower:
        score += 650
    if "/download/" in url_lower or "download" in url_lower:
        score += 550
    if "/bitstream/" in url_lower:
        score += 600
    if "/server/api/core/bitstreams/" in url_lower and "/content" in url_lower:
        score += 700
    if "wp-content/uploads" in url_lower:
        score += 500
    if "files.eric.ed.gov/fulltext" in url_lower:
        score += 500
    if "__cf_chl" in url_lower:
        score += 100
    if "sciencedirect.com/science/article/pii/" in url_lower and "/pdfft" in url_lower:
        score += 850
    if "nature.com/articles/" in url_lower and ".pdf" in url_lower:
        score += 850
    if "tandfonline.com/doi/pdf/" in url_lower:
        score += 850
    if "mdpi.com/" in url_lower and "/pdf" in url_lower:
        score += 700
    if host.endswith(".edu") or ".ac." in host or host.endswith(".gov"):
        score += 60

    return score


def _normalize_candidate(base_url: str, candidate: str) -> str | None:
    token = _decode_escaped_token(candidate).strip()
    if not token:
        return None

    absolute = urljoin(base_url, token)
    parsed = urlparse(unescape(absolute.strip()))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return urlunparse(parsed._replace(fragment=""))


def _decode_escaped_token(token: str) -> str:
    # Typical JS escaping in challenge pages.
    token = token.replace("\\/", "/").replace("&amp;", "&")
    # Decode common unicode escapes conservatively.
    try:
        return bytes(token, "utf-8").decode("unicode_escape")
    except Exception:
        return token


def _extract_cloudflare_tokens(html: str) -> list[str]:
    out: list[str] = []
    for match in _CLOUDFLARE_PATH_PATTERN.findall(html):
        token = _decode_escaped_token(match).strip()
        if token:
            out.append(token)
    return out


def _extract_publisher_candidates(base_url: str, html_unescaped: str = "") -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    parsed = urlparse(base_url)
    host = parsed.netloc.lower()
    path = parsed.path

    # Elsevier / ScienceDirect article pages.
    if "sciencedirect.com" in host:
        pii = None
        m = _SCIENCEDIRECT_PII_PATH.search(path)
        if m:
            pii = m.group(1)
        else:
            m2 = _SCIENCEDIRECT_PII_TOKEN.search(html_unescaped)
            if m2:
                pii = m2.group(1)
        if pii:
            out.append((f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft", 1100))
            out.append(
                (
                    f"https://www.sciencedirect.com/science/article/pii/{pii}/pdfft?isDTMRedir=true&download=true",
                    1150,
                )
            )

    # Nature article pages.
    if "nature.com" in host:
        m = _NATURE_ARTICLE_PATH.search(path)
        if m:
            article_id = m.group(1)
            out.append((f"https://www.nature.com/articles/{article_id}.pdf", 1100))

    # Taylor & Francis.
    if "tandfonline.com" in host:
        m = _TANDFONLINE_DOI_PATH.search(path)
        if m:
            doi = m.group(1).lstrip("/")
            out.append((f"https://www.tandfonline.com/doi/pdf/{doi}", 1050))

    # MDPI article pages.
    if "mdpi.com" in host:
        cleaned_path = path.rstrip("/")
        if cleaned_path and not cleaned_path.lower().endswith("/pdf"):
            out.append((f"https://www.mdpi.com{cleaned_path}/pdf", 980))

    # arXiv HTML landing pages.
    if "arxiv.org" in host:
        m = re.search(r"/html/([^/?#]+)", path, re.I)
        if m:
            arxiv_id = m.group(1)
            out.append((f"https://arxiv.org/pdf/{arxiv_id}.pdf", 1100))

    return out


def _extract_dspace_candidates(soup: BeautifulSoup) -> list[str]:
    out: list[str] = []
    scripts = soup.find_all(
        "script",
        attrs={"id": re.compile(r"dspace-angular-state", re.I), "type": re.compile("json", re.I)},
    )
    for script in scripts:
        payload = (script.string or script.get_text() or "").strip()
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except Exception:
            continue
        for value in _iter_json_strings(data, limit=120_000):
            value_lower = value.lower()
            if (
                ".pdf" in value_lower
                or "/download/" in value_lower
                or "/bitstream/" in value_lower
                or "/server/api/core/bitstreams/" in value_lower
            ):
                out.append(value)
    return out


def _extract_drupal_candidates(soup: BeautifulSoup) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for script in soup.find_all("script", attrs={"data-drupal-selector": "drupal-settings-json"}):
        payload = (script.string or script.get_text() or "").strip()
        if not payload:
            continue
        try:
            data = json.loads(payload)
        except Exception:
            continue

        path_data = data.get("path")
        if not isinstance(path_data, dict):
            continue

        current_path = path_data.get("currentPath")
        current_query = path_data.get("currentQuery")
        if not isinstance(current_path, str) or not isinstance(current_query, dict):
            continue

        file_value = current_query.get("file")
        if not isinstance(file_value, str):
            continue

        if ".pdf" in file_value.lower():
            # Candidate #1: raw file path itself
            out.append((file_value, 850))

            # Candidate #2: reconstructed query endpoint
            query_pairs = [(k, str(v)) for k, v in current_query.items()]
            query_string = urlencode(query_pairs)
            if query_string:
                rebuilt = f"/{current_path.lstrip('/')}?{query_string}"
                out.append((rebuilt, 900))

    return out


def _iter_json_strings(data: Any, *, limit: int) -> list[str]:
    """
    Iterate string values in JSON-like nested structures with a hard limit.
    """
    out: list[str] = []
    stack: list[Any] = [data]

    while stack and len(out) < limit:
        node = stack.pop()
        if isinstance(node, str):
            out.append(node)
            continue
        if isinstance(node, dict):
            stack.extend(node.values())
            continue
        if isinstance(node, list):
            stack.extend(node)
            continue
        if isinstance(node, tuple):
            stack.extend(node)
            continue

    return out
