"""
Identifier classification and extraction utilities.

Pure functions for determining whether identifiers are academic,
extracting identifiers from text lines, and selecting optimal variants.
"""

import re
from urllib.parse import urlparse

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
        if re.fullmatch(r"https?://[^\s\"'<>]+", cleaned):
            pass
        else:
            doi_match = re.search(DOIProcessor.DOI_PATTERN, cleaned, flags=re.IGNORECASE)
            if doi_match:
                cleaned = DOIProcessor._clean_doi_candidate(doi_match.group(0))
            else:
                arxiv_match = re.search(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b", cleaned)
                if arxiv_match:
                    cleaned = arxiv_match.group(0)
                else:
                    url_tokens = DOIProcessor._URL_TOKEN_PATTERN.findall(cleaned)
                    if url_tokens:
                        if len(url_tokens) > 1:
                            cleaned = DOIProcessor._select_primary_url_token(cleaned).strip()
                        else:
                            cleaned = url_tokens[0].strip()

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
    if not identifier:
        return False
    lowered = identifier.lower()
    if lowered.startswith("10."):
        return True
    if lowered.startswith("arxiv:"):
        return True
    return bool(re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", identifier))


def select_retry_identifier(
    normalized_identifier: str, metadata: dict | None
) -> str:
    """Select the best identifier for a retry attempt."""
    if isinstance(metadata, dict):
        for key in ("doi", "DOI"):
            value = metadata.get(key)
            if isinstance(value, str) and value.startswith("10."):
                return value.strip()
    return normalized_identifier


def select_best_identifier_variant(variants: list[str]) -> str:
    """Prefer cleaner identifier variants when multiple raw links normalize to the same key."""

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

    return min(variants, key=_score)
