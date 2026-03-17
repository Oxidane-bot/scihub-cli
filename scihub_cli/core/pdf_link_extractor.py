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
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

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
_ADSABS_ABS_PATH = re.compile(r"/abs/([^/?#]+)", re.I)
_ADSABS_DOI_GATEWAY = re.compile(r"/link_gateway/[^\"'<>\\s]+/doi:([^\s\"'<>]+)", re.I)
_TRAILING_JUNK = re.compile(r"(?i)(?:(?:%7d|%5d|[}\],;])+)$")
_INLINE_HTTP_URL_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.I)
_MDPI_ARTICLE_PATH = re.compile(r"^/\d{4}-\d{4}/\d+/\d+/\d+$")
_NEGATIVE_GATE_TOKENS = (
    "/login",
    "/signin",
    "/account",
    "/subscribe",
    "/purchase",
    "/cart",
    "openathens",
    "shibboleth",
    "cf-turnstile",
    "hcaptcha",
    "g-recaptcha",
    "captcha",
    "recaptcha/api.js",
    "captcha.awswaf.com",
    "captchascript.rendercaptcha",
    "__cf_chl",
    "cf_chl",
    "/cdn-cgi/challenge-platform/",
)


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
        if _is_challenge_or_gate_url(url):
            return
        cleaned = _normalize_candidate(base_url, url)
        if not cleaned:
            return
        normalized_host = urlparse(cleaned).netloc.lower()
        if any(marker in normalized_host for marker in _TRACKER_HOST_MARKERS):
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


def should_try_html_landing(url: str | None) -> bool:
    if not url:
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return 0
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = parsed.netloc.lower()
    heavy_skip = (
        "mdpi.com",
        "wiley.com",
        "onlinelibrary.wiley.com",
        "springer.com",
        "link.springer.com",
        "nature.com",
        "tandfonline.com",
        "sagepub.com",
        "journals.sagepub.com",
        "ieeexplore.ieee.org",
        "ssrn.com",
        "papers.ssrn.com",
        "doi.org",
        "dx.doi.org",
    )
    if any(marker in host for marker in heavy_skip):
        return False
    hints = (
        "repository",
        "repo",
        "eprints",
        "dspace",
        "pure",
        "cris",
        "digitalcommons",
        "escholarship",
        "ojs",
        "journals",
        "library",
        "archive",
        "university",
        "institute",
        "bibl",
        "handle.net",
        "zenodo.org",
        "osf.io",
        "figshare.com",
        "biorxiv.org",
        "medrxiv.org",
    )
    if any(hint in host for hint in hints):
        return True
    return bool(host.endswith(".edu") or ".ac." in host)


def _score_url(url: str) -> int:
    if not url:
        return 0

    url_lower = url.lower()
    if url_lower.startswith(_SKIP_SCHEMES):
        return 0

    try:
        parsed = urlparse(url)
    except ValueError:
        return 0
    host = parsed.netloc.lower()
    if any(marker in host for marker in _TRACKER_HOST_MARKERS):
        return 0
    path_lower = parsed.path.lower()
    if "/thumbnail" in path_lower:
        return 0
    if any(token in url_lower for token in _NEGATIVE_GATE_TOKENS):
        return 0
    if "/auth/" in path_lower:
        return 0
    if any(path_lower.endswith(ext) for ext in _NON_PDF_ASSET_EXTENSIONS):
        return 0

    score = 0
    if url_lower.endswith(".pdf"):
        score += 900
    if ".pdf?" in url_lower or ".pdf&" in url_lower:
        score += 850
    if path_lower.endswith("/pdf"):
        score += 620
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
    if "sciencedirect.com/science/article/pii/" in url_lower and "/pdfft" in url_lower:
        score += 850
    if "nature.com/articles/" in url_lower and ".pdf" in url_lower:
        score += 850
    if "tandfonline.com/doi/pdf/" in url_lower:
        score += 850
    if "onlinelibrary.wiley.com/doi/pdf/" in url_lower or "onlinelibrary.wiley.com/doi/epdf/" in url_lower:
        score += 800
    if "link.springer.com/content/pdf/" in url_lower and url_lower.endswith(".pdf"):
        score += 900
    if "journals.sagepub.com/doi/pdf" in url_lower or "journals.sagepub.com/doi/pdfplus" in url_lower:
        score += 800
    if "mdpi.com/" in url_lower and "/pdf" in url_lower:
        score += 700
    if host.endswith(".edu") or ".ac." in host or host.endswith(".gov"):
        score += 60

    return score


def _normalize_candidate(base_url: str, candidate: str) -> str | None:
    token = _clean_trailing_junk(_decode_escaped_token(candidate).strip())
    token = _extract_primary_inline_url(token) or token
    if not token:
        return None

    if token.lower().startswith("pdf/"):
        base_parsed = urlparse(base_url)
        if base_parsed.netloc in {"pmc.ncbi.nlm.nih.gov", "www.ncbi.nlm.nih.gov"}:
            path = base_parsed.path or ""
            match = re.search(r"/articles/PMC\\d+/?", path, re.I)
            if not match and "/pmc/articles/PMC" in path:
                match = re.search(r"/pmc/articles/PMC\\d+/?", path, re.I)
            if match:
                base_url = urlunparse(
                    base_parsed._replace(
                        path=match.group(0).rstrip("/") + "/",
                        query="",
                        fragment="",
                    )
                )

    absolute = urljoin(base_url, token)
    parsed = urlparse(unescape(absolute.strip()))
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    cleaned_path = _clean_trailing_junk(parsed.path or "")
    cleaned_path = _collapse_repeated_pdf_suffix(cleaned_path)
    cleaned_path = _truncate_after_first_pdf(cleaned_path)
    cleaned_path = _normalize_dspace_api_path(cleaned_path)
    if cleaned_path is None:
        return None
    cleaned_query = _clean_trailing_junk(parsed.query or "")
    return urlunparse(parsed._replace(path=cleaned_path, query=cleaned_query, fragment=""))


def _normalize_dspace_api_path(path: str) -> str | None:
    if not path:
        return path
    lowered = path.lower()
    if "/thumbnail" in lowered:
        return None
    if "/server/api/core/bundles/" in lowered and lowered.rstrip("/").endswith("/bitstreams"):
        return None
    if "/server/api/core/bitstreams/" in lowered and "/content" not in lowered:
        return path.rstrip("/") + "/content"
    return path


def _clean_trailing_junk(value: str) -> str:
    if not value:
        return value
    cleaned = value
    while True:
        updated = _TRAILING_JUNK.sub("", cleaned)
        if updated == cleaned:
            break
        cleaned = updated
    return cleaned


def _collapse_repeated_pdf_suffix(path: str) -> str:
    if not path:
        return path
    return re.sub(r"(\\.pdf)+$", ".pdf", path, flags=re.I)


def _truncate_after_first_pdf(path: str) -> str:
    if not path:
        return path
    lower = path.lower()
    idx = lower.find(".pdf")
    if idx == -1:
        return path
    return path[: idx + 4]


def _extract_primary_inline_url(value: str) -> str | None:
    """
    Recover the most likely URL from markdown/concatenated fragments.
    """
    if not value:
        return None
    matches = _INLINE_HTTP_URL_PATTERN.findall(value)
    if not matches:
        return None
    # Prefer URL-like matches that are likely PDF/download endpoints.
    for match in matches:
        if _score_url(match) > 0:
            return _clean_trailing_junk(match)
    return _clean_trailing_junk(matches[0])


def _is_challenge_or_gate_url(url: str) -> bool:
    lowered = (url or "").lower()
    return any(token in lowered for token in _NEGATIVE_GATE_TOKENS)


def _decode_escaped_token(token: str) -> str:
    # Typical JS escaping in challenge pages.
    token = (
        token.replace("\\/", "/")
        .replace("&amp;", "&")
        .replace("&quot;", "\"")
        .replace("&q;", "\"")
        .replace("&apos;", "'")
    )
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

    # Wiley (onlinelibrary.wiley.com).
    if "onlinelibrary.wiley.com" in host:
        m = re.search(r"/doi/(?:full|abs|pdf|epdf|pdfdirect)/([^?#]+)", path, re.I)
        if not m:
            m = re.search(r"/doi/([^?#]+)", path, re.I)
        if m:
            doi = m.group(1).strip("/")
            if doi.startswith("10."):
                out.append((f"https://onlinelibrary.wiley.com/doi/pdf/{doi}", 1030))
                out.append((f"https://onlinelibrary.wiley.com/doi/epdf/{doi}", 1020))

    # Springer (link.springer.com).
    if "link.springer.com" in host:
        m = re.search(r"/(?:article|chapter|book)/([^?#]+)", path, re.I)
        if m:
            doi = m.group(1).strip("/")
            if doi.startswith("10."):
                out.append((f"https://link.springer.com/content/pdf/{doi}.pdf", 1040))

    # SAGE journals.
    if "journals.sagepub.com" in host:
        m = re.search(r"/doi/(?:abs|full|pdf|pdfplus)/([^?#]+)", path, re.I)
        if not m:
            m = re.search(r"/doi/([^?#]+)", path, re.I)
        if m:
            doi = m.group(1).strip("/")
            if doi.startswith("10."):
                out.append((f"https://journals.sagepub.com/doi/pdf/{doi}", 1020))
                out.append((f"https://journals.sagepub.com/doi/pdfplus/{doi}", 1010))

    # MDPI article pages.
    if "mdpi.com" in host:
        normalized_path = _normalize_mdpi_article_path(parsed.path, parsed.query)
        if normalized_path:
            out.append((f"https://www.mdpi.com{normalized_path}/pdf", 980))

    # SSRN landing pages.
    if "ssrn.com" in host:
        query_params = parse_qs(parsed.query or "")
        abstract_id = (
            (query_params.get("abstractid") or query_params.get("abstract_id") or [None])[0]
        )
        if not abstract_id:
            m = re.search(r"/abstract=([0-9]+)", path, re.I)
            if m:
                abstract_id = m.group(1)
        if abstract_id:
            base = f"https://papers.ssrn.com/sol3/Delivery.cfm?abstractid={abstract_id}"
            out.append((base, 900))
            out.append((f"{base}&type=2", 940))

    # arXiv HTML landing pages.
    if "arxiv.org" in host:
        m = re.search(r"/html/([^/?#]+)", path, re.I)
        if m:
            arxiv_id = m.group(1)
            out.append((f"https://arxiv.org/pdf/{arxiv_id}.pdf", 1100))

    # ADS article pages.
    if "ui.adsabs.harvard.edu" in host:
        m = _ADSABS_ABS_PATH.search(path)
        if m:
            bibcode = m.group(1).strip("/")
            if bibcode:
                out.append((f"https://ui.adsabs.harvard.edu/link_gateway/{bibcode}/PUB_HTML", 780))
        for raw_doi in _ADSABS_DOI_GATEWAY.findall(html_unescaped):
            doi = raw_doi.strip().strip("/")
            doi = _clean_trailing_junk(doi)
            if doi.startswith("10."):
                out.append((f"https://doi.org/{doi}", 820))

    return out


def _normalize_mdpi_article_path(path: str, query: str) -> str | None:
    raw_path = (path or "").strip()
    query_params = parse_qs(query or "")

    if raw_path.rstrip("/") == "/redirect/new_site":
        return_values = query_params.get("return") or []
        if not return_values:
            return None
        raw_path = (return_values[0] or "").strip()

    raw_path = raw_path.rstrip("/")
    raw_path = re.sub(r"/(?:html?|htm)$", "", raw_path, flags=re.I)
    if not raw_path.startswith("/"):
        return None

    lowered = raw_path.lower()
    if any(token in lowered for token in ("[", "]", "(", ")", "{", "}", ")](", "](")):
        return None
    if any(
        lowered.startswith(prefix)
        for prefix in (
            "/about",
            "/topics",
            "/authors",
            "/editors",
            "/reviewers",
            "/journal",
            "/special_issues",
            "/books",
            "/user",
        )
    ):
        return None
    if lowered.endswith("/pdf"):
        return None
    if not _MDPI_ARTICLE_PATH.fullmatch(raw_path):
        return None
    return raw_path


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
            if "/thumbnail" in value_lower:
                continue
            if (
                ".pdf" in value_lower
                or "/download/" in value_lower
                or "/bitstream/" in value_lower
                or "/server/api/core/bitstreams/" in value_lower
            ):
                out.append(value)
                derived = _dspace_bitstream_content_variant(value)
                if derived and derived != value:
                    out.append(derived)
    return out


def _dspace_bitstream_content_variant(value: str) -> str | None:
    """
    DSpace Angular state often exposes bitstream API URLs that need /content appended.
    """
    if not value:
        return None
    parsed = urlparse(value)
    path = parsed.path or ""
    path_lower = path.lower()
    if "/content" in path_lower:
        return None
    if "/server/api/core/bitstreams/" not in path_lower and "/bitstreams/" not in path_lower:
        return None
    new_path = path.rstrip("/") + "/content"
    return urlunparse(parsed._replace(path=new_path, query="", fragment=""))


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
