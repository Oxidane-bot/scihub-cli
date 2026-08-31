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
    _ARXIV_ID_PATTERN = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$", re.IGNORECASE)
    _ARXIV_LEGACY_ID_PATTERN = re.compile(
        r"^[A-Za-z][A-Za-z0-9-]*(?:\.[A-Za-z0-9-]+)?/\d{7}(?:v\d+)?$",
        re.IGNORECASE,
    )
    _URL_TOKEN_PATTERN = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)
    _TRAILING_NOISE = re.compile(r"(?i)(?:[%\s]*(?:%7d|%5d|[}\]),;])+)$")
    _DOI_HOSTS = ("doi.org", "dx.doi.org")
    # A PMCID is an article identifier, not an arbitrary token that can be
    # pulled out of every URL.  Keep the URL allowlist deliberately narrow:
    # these are the public article/rendering hosts used by PMC and Europe PMC.
    # In particular, do not treat a look-alike host or a generic repository
    # path containing ``PMC123`` as evidence that the URL identifies that
    # article.
    _TRUSTED_PMC_HOSTS = frozenset(
        {
            "pmc.ncbi.nlm.nih.gov",
            "ncbi.nlm.nih.gov",
            "www.ncbi.nlm.nih.gov",
            "europepmc.org",
            "www.europepmc.org",
        }
    )
    _PMC_ARTICLE_PATH_RE = re.compile(
        r"^/(?:articles?|pmc/articles)/(PMC\d+)(?:/.*)?$", re.IGNORECASE
    )
    _EUROPE_PMC_RENDER_PATH = "/backend/ptpmcrender.fcgi"
    # A DOI-looking value in an arbitrary PDF URL's query string is not
    # sufficient evidence that the URL serves that DOI.  Keep a small
    # allowlist for publisher endpoints whose documented PDF URL carries the
    # DOI in a query parameter (notably PLOS ``article/file?id=...`` URLs).
    _TRUSTED_DOI_QUERY_HOSTS = (
        "journals.plos.org",
        "plos.org",
        "plosone.org",
    )
    _TRUSTED_DOI_QUERY_KEYS = frozenset({"doi", "id"})
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
    def normalize_identifier(cls, identifier: str) -> str:
        """Return a stable key for deduplicating equivalent identifiers.

        ``normalize_doi`` intentionally keeps non-DOI URLs as URLs because a
        caller may need URL-specific source handlers.  That is useful for a
        single download, but it would otherwise split URL and bare-ID forms of
        the same arXiv/PMC paper into separate batch tasks.  This method adds
        source-aware keys for those identifier families while retaining DOI
        and generic URL normalization for everything else.

        The returned value is an internal identity key, not necessarily a
        value that should be shown to the user or passed to a source handler.
        Callers should retain the original URL as a variant so direct PDF and
        landing-page fallbacks remain available.
        """
        value = html.unescape((identifier or "").strip())
        if not value:
            return ""

        # Prefer an explicit DOI when an unusual DOI suffix or URL happens to
        # contain a token that looks like a PMCID.  This keeps identity keys
        # from accidentally reclassifying a DOI as a PMC article.  For URL
        # inputs, normalize the URL first so a DOI in a trusted publisher path
        # wins over an unrelated ``PMC...`` query/path token.
        parsed = urlparse(value)
        is_http_url = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        if is_http_url or value.lower().startswith(("10.", "doi:")):
            normalized = cls.normalize_doi(value)
            if cls._is_valid_doi(normalized):
                return normalized.lower()

        arxiv_id = cls.extract_arxiv_id(value)
        if arxiv_id:
            return f"arxiv:{arxiv_id.lower()}"

        pmc_id = cls.extract_pmc_id(value)
        if pmc_id:
            return f"pmc:{pmc_id}"

        normalized = cls.normalize_doi(value)
        if cls._is_valid_doi(normalized):
            # DOI resolution is case-insensitive in practice.  Lower-casing
            # only the identity key merges case variants without changing the
            # value used by the downloader or reported in DownloadResult.
            return normalized.lower()

        # Publisher URLs commonly percent-encode the DOI slash (for example
        # ``/doi/pdf/10.1000%2Fxyz``).  Keep the URL as the download variant,
        # but use its decoded DOI for identity grouping when available.
        encoded_doi = cls._extract_doi_from_url(value)
        if encoded_doi:
            return encoded_doi.lower()
        return normalized

    # Explicit aliases make the intent discoverable to callers that do not
    # know this class historically used ``normalize_doi`` for all identifiers.
    dedupe_key = normalize_identifier
    canonicalize_identifier = normalize_identifier

    @classmethod
    def extract_arxiv_id(cls, identifier: str) -> str | None:
        """Extract a canonical arXiv ID from an ID or common arXiv URL."""
        value = html.unescape((identifier or "").strip())
        if not value:
            return None

        value = re.sub(r"^arxiv:\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+", "", value)

        parsed = urlparse(value)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            host = (parsed.hostname or "").lower()
            if host.startswith("www."):
                host = host[4:]
            if host == "arxiv.org" or host.endswith(".arxiv.org"):
                path = unquote(parsed.path or "").strip("/")
                match = re.match(r"(?:abs|pdf|e-print|html)/(.+)$", path, re.IGNORECASE)
                if not match:
                    return None
                value = match.group(1)

        value = value.strip().strip("/[]()<>\"'")
        if value.lower().endswith(".pdf"):
            value = value[:-4]
        if cls._ARXIV_ID_PATTERN.fullmatch(value):
            return value
        # The pre-2007 arXiv namespace uses a category and a seven-digit
        # identifier (for example ``hep-th/9901001``).  Do not split this on
        # the slash: it is part of the identity, not a URL path separator.
        if cls._ARXIV_LEGACY_ID_PATTERN.fullmatch(value):
            return value.lower()
        # A new-style arXiv URL may contain an accidental trailing component
        # after the ID; source handlers only consume the ID.
        value = value.split("/", 1)[0]
        if cls._ARXIV_ID_PATTERN.fullmatch(value):
            return value
        return None

    @classmethod
    def extract_pmc_id(cls, identifier: str) -> str | None:
        """Extract an uppercase PMCID from a safe identifier representation.

        A generic regex search is unsafe here: it turns arbitrary URL query
        parameters (``?pmcid=PMC...``), unrelated path segments, and DOI
        suffixes containing the letters ``PMC`` into a false article identity.
        Accept only an exact bare PMCID or a PMCID in the canonical PMC/NCBI/
        Europe PMC article/rendering paths.
        """
        value = html.unescape((identifier or "").strip())
        if not value:
            return None

        # Batch input commonly contains a bare PMCID.  Do not accept prose,
        # prefixes, query syntax, or a token embedded in another identifier.
        bare_match = re.fullmatch(r"PMC\d+", value, flags=re.IGNORECASE)
        if bare_match:
            return bare_match.group(0).upper()

        try:
            parsed = urlparse(value)
        except ValueError:
            return None
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None

        host = (parsed.hostname or "").lower().rstrip(".")
        if host not in cls._TRUSTED_PMC_HOSTS:
            return None

        path = unquote(parsed.path or "")
        path_match = cls._PMC_ARTICLE_PATH_RE.fullmatch(path)
        if path_match:
            return path_match.group(1).upper()

        # Europe PMC's stable PDF renderer puts the PMCID in ``accid``.  This
        # is the one query form we trust because both the host and endpoint
        # identify a PMC rendering operation; generic query parameters on all
        # other URLs remain intentionally ignored.
        if (
            host in {"europepmc.org", "www.europepmc.org"}
            and path.lower() == cls._EUROPE_PMC_RENDER_PATH
        ):
            for key, query_value in parse_qsl(parsed.query, keep_blank_values=True):
                if key.lower() != "accid":
                    continue
                render_match = re.fullmatch(r"PMC\d+", unquote(query_value).strip(), re.IGNORECASE)
                if render_match:
                    return render_match.group(0).upper()

        return None

    @classmethod
    def _extract_doi_from_url(cls, value: str) -> str | None:
        """Extract a DOI from a trusted URL representation.

        DOI tokens in URL paths are useful for publisher PDF/landing URLs.
        Query strings are deliberately ignored for arbitrary hosts because a
        hostile or unrelated PDF URL can append ``?doi=<other-paper>``.  A
        small set of known publisher hosts is allowed to carry the DOI in
        ``id``/``doi`` query parameters, as PLOS does for printable PDFs.
        """
        parsed = urlparse(value or "")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None

        decoded_path = unquote(parsed.path or "")
        match = re.search(cls.DOI_PATTERN, cls._strip_trailing_noise(decoded_path))
        if match is None and cls._is_trusted_doi_query_host(parsed.hostname or ""):
            for key, query_value in parse_qsl(parsed.query, keep_blank_values=True):
                if key.lower() not in cls._TRUSTED_DOI_QUERY_KEYS:
                    continue
                match = re.search(
                    cls.DOI_PATTERN,
                    cls._strip_trailing_noise(unquote(query_value)),
                )
                if match is not None:
                    break
        if match is None:
            return None

        candidate = cls._clean_doi_candidate(match.group(0))
        # A direct publisher PDF URL may put a file extension immediately
        # after the DOI.  The extension belongs to the URL representation, not
        # to the DOI identity.
        if candidate.lower().endswith(".pdf"):
            candidate = candidate[:-4]
        return candidate if cls._is_valid_doi(candidate) else None

    @classmethod
    def _is_trusted_doi_query_host(cls, host: str) -> bool:
        lowered = (host or "").lower().rstrip(".")
        if lowered.startswith("www."):
            lowered = lowered[4:]
        return any(
            lowered == marker or lowered.endswith(f".{marker}")
            for marker in cls._TRUSTED_DOI_QUERY_HOSTS
        )

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

            # Publisher URLs often percent-encode the DOI slash.  Try the
            # decoded URL before treating it as a generic landing page.  This
            # also strips a trailing ``.pdf`` that belongs to a direct URL.
            decoded_doi = cls._extract_doi_from_url(identifier)
            if decoded_doi:
                return decoded_doi

            # Try to find DOI in the URL path.  Never inspect the complete URL
            # here: a query-only DOI on an untrusted PDF host is not an
            # identity assertion for the served document.
            doi_match = re.search(
                cls.DOI_PATTERN,
                cls._strip_trailing_noise(unquote(parsed.path or "")),
            )
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
