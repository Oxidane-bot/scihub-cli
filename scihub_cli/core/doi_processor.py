"""
DOI and URL normalization utilities.
"""

import html
import re
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

from ..utils.logging import get_logger

logger = get_logger(__name__)


class DOIProcessor:
    """Handles DOI normalization and URL formatting."""

    DOI_PATTERN = r'\b10\.\d{4,}(?:\.\d+)*\/(?:(?!["&\'<>])\S)+\b'
    _STRICT_DOI_PATTERN = re.compile(r"^10\.\d{4,9}(?:\.\d+)*/[-._;()/:A-Za-z0-9]+$")
    _URL_TOKEN_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
    _TRAILING_NOISE = re.compile(r"(?i)(?:[%\s]*(?:%7d|%5d|[}\]),;])+)$")
    _DOI_HOSTS = ("doi.org", "dx.doi.org")
    _MARKDOWN_SPLIT_MARKERS = ("](", ")](", ">](", "})(", "](http", "](https")
    _TRACKING_QUERY_KEYS = {
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "utm_id",
        "gclid",
        "fbclid",
        "mc_cid",
        "mc_eid",
    }

    @classmethod
    def normalize_doi(cls, identifier: str) -> str:
        """Convert URL or DOI to a normalized DOI format."""
        identifier = html.unescape(identifier.strip())
        identifier = re.sub(r"^doi[:\s]+", "", identifier, flags=re.IGNORECASE)
        identifier = cls._select_primary_url_token(identifier)
        identifier = re.sub(r"\s+", "", identifier)
        identifier = cls._strip_trailing_noise(identifier)
        identifier = cls._strip_markdown_tail(identifier)
        # If it's already a DOI
        cleaned_identifier = cls._clean_doi_candidate(identifier)
        if cls._is_valid_doi(cleaned_identifier):
            return cleaned_identifier

        # If it's a URL, try to extract DOI
        parsed = urlparse(identifier)
        if parsed.netloc:
            path = parsed.path
            if cls._is_crossref_api_host(parsed.netloc):
                doi_candidate = cls._extract_doi_from_crossref_api_path(path)
                if cls._is_valid_doi(doi_candidate):
                    return doi_candidate
            # Extract DOI from common URL patterns
            if cls._is_doi_host(parsed.netloc):
                doi_candidate = cls._extract_doi_from_doi_url(path)
                if cls._is_valid_doi(doi_candidate):
                    return doi_candidate
                return cls._canonicalize_url_identifier(identifier)

            # Try to find DOI in the URL path
            doi_match = re.search(cls.DOI_PATTERN, cls._strip_trailing_noise(identifier))
            if doi_match:
                matched = cls._clean_doi_candidate(doi_match.group(0))
                if cls._is_valid_doi(matched):
                    return matched

            return cls._canonicalize_url_identifier(identifier)

        # Return as is if we can't normalize
        return identifier

    @classmethod
    def format_doi_for_url(cls, doi: str) -> str:
        """Format DOI for use in Sci-Hub URL."""
        # Replace / with @ for Sci-Hub URL format
        formatted = doi.replace("/", "@")
        # Handle parentheses and other special characters
        formatted = quote(formatted, safe="@")
        return formatted

    @classmethod
    def _strip_trailing_noise(cls, value: str) -> str:
        if not value:
            return value
        cleaned = value
        while True:
            updated = cls._TRAILING_NOISE.sub("", cleaned)
            if updated == cleaned:
                break
            cleaned = updated
        return cleaned

    @classmethod
    def _is_valid_doi(cls, candidate: str) -> bool:
        return bool(candidate and cls._STRICT_DOI_PATTERN.fullmatch(candidate))

    @classmethod
    def _is_doi_host(cls, host: str) -> bool:
        lowered = (host or "").lower()
        if lowered.startswith("www."):
            lowered = lowered[4:]
        return lowered in cls._DOI_HOSTS

    @classmethod
    def _is_crossref_api_host(cls, host: str) -> bool:
        lowered = (host or "").lower()
        if lowered.startswith("www."):
            lowered = lowered[4:]
        return lowered == "api.crossref.org"

    @classmethod
    def _select_primary_url_token(cls, raw: str) -> str:
        if not raw:
            return raw
        tokens = cls._URL_TOKEN_PATTERN.findall(raw)
        if len(tokens) < 2:
            return raw
        # Markdown snippets often append the real target URL last: ...](https://target)
        if any(marker in raw for marker in cls._MARKDOWN_SPLIT_MARKERS):
            return tokens[-1]
        return tokens[0]

    @classmethod
    def _strip_markdown_tail(cls, value: str) -> str:
        cleaned = value
        for marker in cls._MARKDOWN_SPLIT_MARKERS:
            if marker in cleaned:
                cleaned = cleaned.split(marker, 1)[0]
        return cleaned

    @classmethod
    def _extract_doi_from_doi_url(cls, path: str) -> str:
        decoded_path = unquote(path or "")
        candidate = cls._clean_doi_candidate(decoded_path.strip("/"))
        if cls._is_valid_doi(candidate):
            return candidate
        match = re.search(cls.DOI_PATTERN, decoded_path)
        if not match:
            return candidate
        extracted = cls._clean_doi_candidate(match.group(0))
        return extracted

    @classmethod
    def _extract_doi_from_crossref_api_path(cls, path: str) -> str:
        decoded = unquote(path or "").strip("/")
        if not decoded:
            return decoded
        candidate = decoded.split("/", 1)[1] if decoded.lower().startswith("works/") else decoded
        return cls._clean_doi_candidate(candidate)

    @classmethod
    def _canonicalize_url_identifier(cls, value: str) -> str:
        parsed = urlparse((value or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return value

        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]

        path = cls._clean_trailing_url_path(parsed.path or "")
        if path != "/" and path.endswith("/"):
            path = path[:-1]
        if not path:
            path = "/"

        params: list[tuple[str, str]] = []
        for key, raw_value in parse_qsl(parsed.query, keep_blank_values=True):
            lowered_key = key.lower()
            if lowered_key.startswith("utm_") or lowered_key in cls._TRACKING_QUERY_KEYS:
                continue
            params.append((key, raw_value))
        query = urlencode(params, doseq=True)

        return urlunparse(
            (
                parsed.scheme.lower(),
                host,
                path,
                "",
                query,
                "",
            )
        )

    @classmethod
    def _clean_trailing_url_path(cls, path: str) -> str:
        if not path:
            return path
        cleaned = path
        while True:
            updated = cls._TRAILING_NOISE.sub("", cleaned)
            if updated == cleaned:
                break
            cleaned = updated
        return cleaned

    @classmethod
    def _clean_doi_candidate(cls, value: str) -> str:
        candidate = cls._strip_markdown_tail(value or "")
        candidate = cls._strip_trailing_noise(candidate)
        candidate = candidate.split("?", 1)[0]
        if "http://" in candidate[1:] or "https://" in candidate[1:]:
            split_http = re.split(r"https?://", candidate, maxsplit=1)
            if split_http:
                candidate = split_http[0]
        candidate = candidate.rstrip(")}],;")
        # Fix common markdown/CSV corruption where "/" becomes "_".
        if "/" not in candidate and "_" in candidate and candidate.startswith("10."):
            prefix, suffix = candidate.split("_", 1)
            if prefix.startswith("10.") and suffix:
                candidate = f"{prefix}/{suffix}"
        # Trim obvious concatenated prose tails like "...420Digital".
        prose_tail = re.match(
            r"^(10\.\d{4,9}(?:\.\d+)*/[-._;()/:A-Za-z0-9]*\d)([A-Z][a-z]{3,})$",
            candidate,
        )
        if prose_tail:
            trimmed = prose_tail.group(1)
            if cls._is_valid_doi(trimmed):
                candidate = trimmed
        return cls._strip_trailing_noise(candidate)
