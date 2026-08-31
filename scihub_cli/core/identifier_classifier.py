"""
Identifier classification and extraction utilities.

Pure functions for determining whether identifiers are academic,
extracting identifiers from text lines, and selecting optimal variants.
"""

import re
from urllib.parse import unquote, urlparse

from ..config.domains import (
    ACADEMIC_HOST_HINTS,
    ACADEMIC_HOST_MARKERS,
    ACADEMIC_PATH_HINTS,
    NON_ACADEMIC_HOST_EXTRA_MARKERS,
    NON_ACADEMIC_PATH_HINTS,
)
from .doi_processor import DOIProcessor


def is_probably_academic_identifier(
    identifier: str,
    *,
    is_obvious_non_academic_host=None,
) -> bool:
    """Determine if an identifier is likely from an academic source."""
    token = (identifier or "").strip()
    if not token:
        return False
    lowered = token.lower()

    if lowered.startswith("10.") or lowered.startswith("arxiv:"):
        return True

    parsed = urlparse(token)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return True

    host = parsed.netloc.lower()
    if is_obvious_non_academic_host and is_obvious_non_academic_host(host):
        return False
    if host.startswith("www."):
        host = host[4:]
    if any(marker in host for marker in NON_ACADEMIC_HOST_EXTRA_MARKERS):
        return False

    path = (parsed.path or "").lower()
    if path.endswith(
        (
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".webp",
            ".mp4",
            ".mp3",
            ".css",
            ".js",
            ".ico",
        )
    ):
        return False

    path_query = f"{path}?{(parsed.query or '').lower()}"
    if any(hint in path_query for hint in NON_ACADEMIC_PATH_HINTS):
        return False

    if host.endswith(".edu") or host.endswith(".gov") or ".ac." in host:
        return True
    if any(marker in host for marker in ACADEMIC_HOST_MARKERS):
        return True
    if any(hint in host for hint in ACADEMIC_HOST_HINTS):
        return True

    if any(hint in path_query for hint in ACADEMIC_PATH_HINTS):
        return True

    return bool(re.search(r"10\.[0-9]{4,9}/[-._;()/:a-z0-9]+", path_query, flags=re.I))


def extract_identifier_from_line(line: str) -> str | None:
    """Extract a clean identifier from a raw text line."""
    if not line:
        return None

    cleaned = line.strip()
    if not cleaned:
        return None

    if "\t" in cleaned:
        parts = [part.strip() for part in cleaned.split("\t") if part.strip()]
        if parts:
            cleaned = parts[-1]

    cleaned = re.sub(r"\s*\[[^\]]+\]\s*$", "", cleaned).strip()

    tokens = cleaned.split()
    if len(tokens) >= 3 and tokens[-2].lower() in {"success", "failed", "skipped"}:
        cleaned = tokens[-1]

    pdf_url_match = re.search(r"https?://[^\s\"'<>]+?\.pdf(?:\?[^\s\"'<>]+)?", cleaned)
    if pdf_url_match:
        cleaned = pdf_url_match.group(0)
    else:
        # Preserve a complete URL before scanning for a DOI token.  A DOI in
        # an arbitrary URL query (for example ``?doi=...``) is not proof that
        # the URL serves that paper; DOIProcessor can inspect trusted URL
        # paths/hosts later without collapsing the URL to the query value.
        url_tokens = DOIProcessor._URL_TOKEN_PATTERN.findall(cleaned)
        if url_tokens:
            if len(url_tokens) > 1:
                cleaned = DOIProcessor._select_primary_url_token(cleaned).strip()
            else:
                cleaned = url_tokens[0].strip()
        else:
            doi_match = re.search(DOIProcessor.DOI_PATTERN, cleaned, flags=re.IGNORECASE)
            if doi_match:
                cleaned = DOIProcessor._clean_doi_candidate(doi_match.group(0))
            else:
                arxiv_match = re.search(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b", cleaned)
                if arxiv_match:
                    cleaned = arxiv_match.group(0)

    cleaned = DOIProcessor._strip_trailing_noise(cleaned).strip(")];,")
    cleaned = cleaned.strip("[]()<>\"'")
    if cleaned.lower().startswith("10.") and cleaned.lower().endswith(".pdf"):
        cleaned = cleaned[:-4]
    if cleaned.lower().startswith("10.") and cleaned.endswith("&"):
        cleaned = cleaned[:-1]
    return cleaned.strip() or None


def should_fast_fail_url(identifier: str, normalized_identifier: str) -> bool:
    """Determine if a URL should be fast-failed (skipped) based on host/path patterns."""
    parsed = urlparse(normalized_identifier or "")
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False

    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]

    path = (parsed.path or "").lower()
    if path.endswith(
        (
            ".png",
            ".jpg",
            ".jpeg",
            ".gif",
            ".svg",
            ".webp",
            ".mp4",
            ".mp3",
            ".css",
            ".js",
            ".ico",
        )
    ):
        return True

    if re.search(DOIProcessor.DOI_PATTERN, normalized_identifier, flags=re.IGNORECASE):
        return False

    if path.endswith(".pdf"):
        return False

    if host.endswith("mdpi.com"):
        mdpi_non_paper_prefixes = (
            "/topics",
            "/topic",
            "/journal/",
            "/special_issues",
            "/topical_advisory_panel",
            "/about",
            "/editors",
            "/authors",
            "/user/",
            "/institutional",
            "/news",
            "/events",
            "/search",
            "/susy",
        )
        if path == "/topics" or path.startswith(mdpi_non_paper_prefixes):
            return True

    if "sciencedirect.com" in host and "/craft/" in path:
        return True

    fast_fail_hosts = {
        "researchgate.net",
        "www.researchgate.net",
        "academia.edu",
        "www.academia.edu",
        "sk.sagepub.com",
        "www.sk.sagepub.com",
        "susy.mdpi.com",
        "www.susy.mdpi.com",
    }
    return host in fast_fail_hosts


def should_retry_sources_after_download_failure(error_msg: str) -> bool:
    """Determine if source retry is worthwhile after a download failure."""
    lowered = (error_msg or "").lower()
    if not lowered:
        return False
    if "skipped non-academic" in lowered:
        return False

    # Downloaders commonly return just ``HTTP <status>``.  Do not rely only
    # on descriptive words such as "rate limit": a bare 408/425/429 must
    # trigger a different-source lookup, while ordinary 4xx failures remain
    # permanent for this policy.  A 403 is retained as an alternate-provider
    # fallback signal because access denial is endpoint-specific here.
    http_statuses = [
        int(match.group(1))
        for match in re.finditer(
            r"\b(?:http(?:error)?(?:[._ ]+(?:status(?:[_ ]+code)?|code))?"
            r"|status(?:[_ ]+code)?"
            r"|response(?:[._ ]+status(?:[_ ]+code)?)?)"
            r"\s*[:#=-]?\s*([1-5]\d{2})\b",
            lowered,
        )
    ]
    if http_statuses:
        if any(status in {408, 425, 429} or 500 <= status < 600 for status in http_statuses):
            return True
        return all(status == 403 for status in http_statuses)

    # A metadata source only proves that a URL was advertised; it does not
    # prove that the file endpoint is healthy.  Transient endpoint failures
    # (timeouts, throttling, and 5xx responses) are a strong signal to try a
    # different OA provider instead of stopping after the selected URL.
    if re.search(r"\b5\d{2}\b", lowered):
        return True
    if any(
        token in lowered
        for token in (
            "timeout",
            "timed out",
            "connection error",
            "temporarily unavailable",
            "service unavailable",
            "rate limit",
            "too many requests",
            "deadline exceeded",
            "validation failed",
            "not a valid pdf",
            "missing pdf header",
        )
    ):
        return True
    return any(
        token in lowered
        for token in (
            "access denied",
            "403",
            "html instead of pdf",
            "html response",
            "challenge",
            "captcha",
            "cloudflare",
            "blocked",
            "skipped challenge-heavy pdf url",
        )
    )


def is_retryable_identifier(identifier: str) -> bool:
    """Check if an identifier is worth retrying with different sources."""
    candidate = (identifier or "").strip()
    if not candidate:
        return False
    lowered = candidate.lower()
    if lowered.startswith("10."):
        return True
    if lowered.startswith("arxiv:"):
        return True
    if DOIProcessor.extract_arxiv_id(candidate):
        return True
    if DOIProcessor.extract_pmc_id(candidate):
        return True
    return bool(re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", candidate))


def select_retry_identifier(normalized_identifier: str, metadata: dict | None) -> str:
    """Select an identifier for a source retry without changing paper identity.

    A DOI scraped from a landing page is only metadata, not proof that the
    requested URL identifies that DOI.  Preserve strong identifiers (DOIs,
    PMCID, and arXiv IDs/URLs) so a broken endpoint for one paper cannot make
    a retry query a different paper.  Generic landing URLs remain eligible for
    the historical metadata-DOI fallback because they do not carry a stable
    paper identifier themselves.
    """
    candidate = (normalized_identifier or "").strip()
    if not candidate:
        candidate = normalized_identifier

    # ``normalized_identifier`` is normally already normalized by
    # ``DOIProcessor``.  Keep this check source-aware so PMC/arXiv URLs retain
    # their URL-specific handlers on a retry, rather than being replaced by a
    # DOI scraped from possibly unrelated page markup.
    if (
        DOIProcessor._is_valid_doi(candidate)
        or DOIProcessor.extract_pmc_id(candidate)
        or DOIProcessor.extract_arxiv_id(candidate)
    ):
        return candidate

    if isinstance(metadata, dict):
        for key in ("doi", "DOI"):
            value = metadata.get(key)
            if isinstance(value, str) and value.startswith("10."):
                return value.strip()
    return candidate


def select_best_identifier_variant(variants: list[str]) -> str:
    """Prefer the most useful download variant for a deduplicated paper.

    A batch can contain a bare DOI/ID as well as a URL for the same paper.  A
    bare identifier is compact, but choosing it as the sole representative
    discards URL-specific handlers (direct PDF, PMC rendering, or an article
    landing page).  Rank variants by how much download information they carry,
    then retain the existing cleanliness/length tie-breakers.
    """

    if not variants:
        return ""

    def _variant_rank(value: str) -> int:
        candidate = (value or "").strip()
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return 40

        path = (parsed.path or "").lower()
        query = (parsed.query or "").lower()
        host = (parsed.hostname or "").lower()

        # A direct PDF or render endpoint is the strongest fallback: it can be
        # handed to Direct PDF/PMC without first resolving another identifier.
        if (
            path.endswith(".pdf")
            or "/pdf/" in path
            or path.endswith("/pdf")
            or "pdf=render" in query
            or "blobtype=pdf" in query
        ):
            # A random PDF endpoint can carry an unrelated DOI in its query
            # string.  If such a URL is ever presented alongside a bare DOI,
            # keep the bare DOI as the safer representative; source-aware
            # deduplication normally keeps these variants in separate groups.
            if _is_untrusted_query_doi_url(candidate):
                return 50
            return 0

        # Preserve article pages for HTML/PMC extraction.  arXiv abs/html and
        # publisher pages both carry more routing information than a bare ID.
        if (host == "arxiv.org" or host.endswith(".arxiv.org")) and path.startswith(
            ("/abs/", "/html/", "/e-print/")
        ):
            return 5
        if DOIProcessor._is_doi_host(host):
            return 20
        return 10

    def _score(value: str) -> tuple[int, int]:
        lowered = (value or "").lower()
        penalty = 0
        penalty += lowered.count("](") * 8
        penalty += lowered.count(")](") * 8
        penalty += lowered.count("{") * 4
        penalty += lowered.count("}") * 4
        penalty += lowered.count("[") * 3
        penalty += lowered.count("]") * 3
        penalty += lowered.count("?utm_") * 6
        penalty += lowered.count("http://") + lowered.count("https://")
        return penalty, len(value or "")

    return min(variants, key=lambda value: (_variant_rank(value), *_score(value)))


def _is_untrusted_query_doi_url(value: str) -> bool:
    """Return whether a direct PDF URL has a DOI only in an untrusted query.

    This is intentionally conservative and only affects variant ranking.  A
    URL that is the sole input remains usable, while a bare DOI is preferred
    when the URL's query is the only evidence that both values refer to one
    paper.  DOIProcessor owns the publisher allowlist and path parsing.
    """
    parsed = urlparse((value or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.query:
        return False
    if DOIProcessor._is_trusted_doi_query_host(parsed.hostname or ""):
        return False
    if DOIProcessor._extract_doi_from_url(value):
        return False
    return bool(re.search(DOIProcessor.DOI_PATTERN, unquote(parsed.query), flags=re.IGNORECASE))
