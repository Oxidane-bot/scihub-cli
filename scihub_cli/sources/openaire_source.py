"""
OpenAIRE search API source implementation.

Uses the OpenAIRE search API to resolve DOIs to OA repository links.
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import unquote, urlparse

import requests
from requests.adapters import HTTPAdapter

from ..core.pdf_link_extractor import derive_publisher_pdf_candidates, should_try_html_landing
from ..utils.logging import get_logger
from ..utils.retry import (
    APIRetryConfig,
    PermanentError,
    RetryableError,
    retry_with_classification,
)
from .base import PaperSource

logger = get_logger(__name__)


class OpenAireSource(PaperSource):
    """OpenAIRE open-access source."""

    _RATE_LIMIT_COOLDOWN_SECONDS = 120

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
        self.base_url = "https://api.openaire.eu/search/researchProducts"
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update({"User-Agent": "scihub-cli/1.0 (OpenAIRE OA lookup)"})
        adapter = HTTPAdapter(pool_connections=32, pool_maxsize=32)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

        self._metadata_cache: dict[str, dict[str, Any] | None] = {}
        self._rate_limited_until: float | None = None
        self.retry_config = APIRetryConfig()
        if self.fast_fail:
            self.retry_config.max_attempts = 2
            self.retry_config.base_delay = 0.0
            self.retry_config.max_delay = 0.0

    @property
    def name(self) -> str:
        return "OpenAIRE"

    def can_handle(self, doi: str) -> bool:
        return doi.startswith("10.")

    def get_metadata(self, doi: str) -> dict[str, Any] | None:
        return self._fetch_metadata(doi)

    def get_pdf_url(self, doi: str) -> str | None:
        metadata = self._fetch_metadata(doi)
        if not metadata:
            return None
        pdf_url = metadata.get("pdf_url")
        if not pdf_url:
            logger.debug(f"[OpenAIRE] No PDF URL available for {doi}")
            return None
        if self._should_skip_pdf_url(pdf_url):
            logger.info(f"[OpenAIRE] Fast-fail skip challenge-heavy PDF URL: {pdf_url}")
            return None
        logger.info(f"[OpenAIRE] Found OA paper: {doi}")
        logger.debug(f"[OpenAIRE] PDF URL: {pdf_url}")
        return pdf_url

    def _is_rate_limited(self) -> bool:
        if self._rate_limited_until is None:
            return False
        return time.monotonic() < self._rate_limited_until

    def _fetch_metadata(self, doi: str) -> dict[str, Any] | None:
        if doi in self._metadata_cache:
            logger.debug(f"[OpenAIRE] Using cached metadata for {doi}")
            return self._metadata_cache[doi]

        if self._is_rate_limited():
            cooldown = (
                self._rate_limited_until - time.monotonic() if self._rate_limited_until else 0
            )
            logger.info(
                "[OpenAIRE] Skipping API due to recent rate limit (cooldown %.0fs)",
                cooldown,
            )
            return None

        def _attempt_fetch():
            return self._fetch_from_api(doi)

        try:
            metadata = retry_with_classification(
                _attempt_fetch, self.retry_config, f"OpenAIRE API for {doi}"
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
            params = {"doi": doi, "format": "json"}
            response = self.session.get(self.base_url, params=params, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json() or {}
                results = self._ensure_list(
                    ((data.get("response") or {}).get("results") or {}).get("result")
                )
                if not results:
                    raise PermanentError("DOI not found")

                # OpenAIRE returns a deduplicated work with many related PIDs
                # and repository instances.  Prefer the result that actually
                # carries the requested DOI before considering related records;
                # otherwise a neighboring PID can win merely because it was
                # serialized first.
                matching_results = [
                    result
                    for result in results
                    if isinstance(result, dict)
                    and self._metadata_matches_doi(result.get("metadata"), doi)
                ]
                ordered_results = matching_results + [
                    result for result in results if result not in matching_results
                ]

                for result in ordered_results:
                    metadata = result.get("metadata") if isinstance(result, dict) else None
                    if not isinstance(metadata, dict):
                        continue

                    ranked_url_records = self._extract_ranked_url_records(metadata, doi=doi)
                    has_open_url = any(is_open for _url, _rank, is_open in ranked_url_records)
                    if not ranked_url_records:
                        continue

                    pdf_url = None
                    # Keep exact-PID candidates together.  A related record's
                    # PDF must not win just because it looks more directly
                    # downloadable than the exact record's landing page.
                    for match_rank in sorted(
                        {rank for _url, rank, _is_open in ranked_url_records}, reverse=True
                    ):
                        rank_urls = [
                            url for url, rank, _is_open in ranked_url_records if rank == match_rank
                        ]
                        landing_candidates: list[str] = []
                        for url in rank_urls:
                            if self._looks_like_pdf_url(url):
                                pdf_url = url
                                break
                            landing_candidates.append(url)

                        if pdf_url:
                            break

                        derived = self._derive_pdf_from_landing_urls(landing_candidates)
                        if derived:
                            if self._should_skip_pdf_url(derived):
                                logger.info(
                                    "[OpenAIRE] Fast-fail skip derived PDF candidate: %s",
                                    derived,
                                )
                            else:
                                pdf_url = derived

                        if not pdf_url:
                            for landing in landing_candidates:
                                if should_try_html_landing(landing):
                                    pdf_url = landing
                                    break

                        if pdf_url:
                            break

                    if pdf_url:
                        title, year = self._extract_selected_metadata(
                            metadata, doi=doi, match_rank=match_rank
                        )
                        return {
                            "title": title or "",
                            "year": year,
                            "journal": "",
                            "is_oa": has_open_url,
                            "pdf_url": pdf_url,
                            "source": "OpenAIRE",
                        }

                raise PermanentError("No OA URL found")

            if response.status_code == 404:
                raise PermanentError("DOI not found")
            if response.status_code == 429:
                if self.fast_fail:
                    self._rate_limited_until = time.monotonic() + self._RATE_LIMIT_COOLDOWN_SECONDS
                    raise PermanentError("Rate limited")
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
    def _ensure_list(value: Any) -> list[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    @staticmethod
    def _extract_text_values(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return [str(value)]
        if isinstance(value, list):
            values: list[str] = []
            for item in value:
                values.extend(OpenAireSource._extract_text_values(item))
            return values
        if isinstance(value, dict):
            for key in ("$", "@value"):
                if key in value and value.get(key) is not None:
                    return [str(value.get(key))]
        return []

    def _extract_instance_urls(self, instance: dict[str, Any]) -> list[str]:
        urls: list[str] = []
        for item in self._ensure_list(instance.get("url")):
            urls.extend(self._extract_text_values(item))
        for webresource in self._ensure_list(instance.get("webresource")):
            if isinstance(webresource, dict):
                urls.extend(self._extract_text_values(webresource.get("url")))
            else:
                urls.extend(self._extract_text_values(webresource))
        return [url.strip() for url in urls if isinstance(url, str) and self._is_http_url(url)]

    @staticmethod
    def _is_http_url(url: str) -> bool:
        """Return whether *url* is an absolute HTTP(S) URL.

        OpenAIRE occasionally emits repository transport links such as
        ``ftp://`` alongside browser-downloadable links.  They are not
        candidates for the downloader, so reject them at extraction time.
        """

        if not isinstance(url, str) or not url.strip():
            return False
        try:
            parsed = urlparse(url.strip())
        except ValueError:
            return False
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)

    def _extract_accessright(self, instance: dict[str, Any]) -> str:
        access = instance.get("accessright")
        if isinstance(access, dict):
            classid = (
                access.get("@classid")
                or access.get("@classname")
                or access.get("$")
                or access.get("@value")
            )
            return str(classid or "").upper()
        if isinstance(access, str):
            return access.upper()
        return ""

    @classmethod
    def _normalize_doi_for_match(cls, value: Any) -> str:
        """Normalize a DOI/PID value for exact, case-insensitive matching."""

        if value is None:
            return ""
        text = unquote(str(value)).strip()
        if not text:
            return ""
        lowered = text.lower()
        for prefix in (
            "https://doi.org/",
            "http://doi.org/",
            "https://dx.doi.org/",
            "http://dx.doi.org/",
            "doi:",
        ):
            if lowered.startswith(prefix):
                text = text[len(prefix) :].strip()
                break
        return text.rstrip(".,; ").lower()

    @classmethod
    def _node_pid_values(cls, node: Any) -> list[str]:
        if not isinstance(node, dict):
            return []
        values: list[str] = []
        for key in ("pid", "originalId", "alternateidentifier", "alternateIdentifier"):
            for item in cls._ensure_list(node.get(key)):
                values.extend(cls._extract_text_values(item))
        return values

    @classmethod
    def _node_matches_doi(cls, node: Any, doi: str) -> bool:
        requested = cls._normalize_doi_for_match(doi)
        if not requested:
            return False
        return any(
            cls._normalize_doi_for_match(value) == requested for value in cls._node_pid_values(node)
        )

    @classmethod
    def _metadata_matches_doi(cls, metadata: Any, doi: str) -> bool:
        """Check top-level and child PID fields without treating URLs as PIDs."""

        if not isinstance(metadata, dict):
            return False
        entity = metadata.get("oaf:entity") or {}
        result = entity.get("oaf:result") or {}
        if cls._node_matches_doi(result, doi):
            return True
        children = result.get("children") or {}
        for child in cls._ensure_list(children.get("result")):
            if cls._node_matches_doi(child, doi):
                return True
        for child in cls._ensure_list(children.get("instance")):
            if cls._nested_node_matches_doi(child, doi):
                return True
        return False

    @classmethod
    def _nested_node_matches_doi(cls, node: Any, doi: str) -> bool:
        """Find a DOI/PID on an instance wrapper and its nested instance."""

        if not isinstance(node, dict):
            return False
        if cls._node_matches_doi(node, doi):
            return True
        for nested in cls._ensure_list(node.get("instance")):
            if cls._nested_node_matches_doi(nested, doi):
                return True
        return False

    def _iter_instance_records(
        self, metadata: dict[str, Any], *, doi: str | None = None
    ) -> list[tuple[dict[str, Any], int]]:
        """Return ``(instance, match_rank)`` records from OpenAIRE's variants.

        The API uses both a singular object and an array for ``instance`` and
        ``webresource`` depending on the repository transformer.  The exact
        DOI can live on a child result while its PDF URL is nested one level
        deeper, so retain that association for candidate ranking.  A child
        PID match (rank 2) is stronger than only matching the deduplicated
        parent record (rank 1), which may list several related PIDs.
        """

        entity = metadata.get("oaf:entity") or {}
        result = entity.get("oaf:result") or {}
        parent_exact = self._node_matches_doi(result, doi or "")
        children = result.get("children") or {}
        records: list[tuple[dict[str, Any], int]] = []

        for child in self._ensure_list(children.get("result")):
            if not isinstance(child, dict):
                continue
            child_match = self._node_matches_doi(child, doi or "")
            match_rank = 2 if child_match else (1 if parent_exact else 0)
            records.extend(
                self._iter_nested_instance_records(
                    child.get("instance"), doi=doi or "", inherited_rank=match_rank
                )
            )

        for instance in self._ensure_list(children.get("instance")):
            records.extend(
                self._iter_nested_instance_records(
                    instance,
                    doi=doi or "",
                    inherited_rank=1 if parent_exact else 0,
                )
            )

        # Some older responses put an instance directly on oaf:result.
        records.extend(
            self._iter_nested_instance_records(
                result.get("instance"), doi=doi or "", inherited_rank=1 if parent_exact else 0
            )
        )
        return records

    def _iter_nested_instance_records(
        self, value: Any, *, doi: str, inherited_rank: int
    ) -> list[tuple[dict[str, Any], int]]:
        """Unwrap OpenAIRE's optional ``children.instance`` containers.

        Depending on the transformer, ``children.instance`` can be an
        instance object, a list of instances, or a wrapper whose own
        ``instance`` member contains the real object(s).  PID fields on the
        wrapper still identify the nested instance, so carry the strongest
        match rank through the unwrap.
        """

        if isinstance(value, list):
            records: list[tuple[dict[str, Any], int]] = []
            for item in value:
                records.extend(
                    self._iter_nested_instance_records(item, doi=doi, inherited_rank=inherited_rank)
                )
            return records
        if not isinstance(value, dict):
            return []

        match_rank = 2 if self._node_matches_doi(value, doi) else inherited_rank
        nested = value.get("instance")
        if nested is not None:
            records: list[tuple[dict[str, Any], int]] = []
            # Be tolerant of a transformer that puts URL fields on the
            # wrapper as well as on its nested instance.
            if self._extract_instance_urls(value):
                records.append((value, match_rank))
            records.extend(
                self._iter_nested_instance_records(nested, doi=doi, inherited_rank=match_rank)
            )
            return records
        return [(value, match_rank)]

    def _extract_ranked_url_records(
        self, metadata: dict[str, Any], *, doi: str | None = None
    ) -> list[tuple[str, int, bool]]:
        """Extract ``(url, PID rank, OA)`` records in download order."""

        records = self._iter_instance_records(metadata, doi=doi)
        ranked: list[tuple[int, int, int, int, str, bool]] = []
        for order, (instance, match_rank) in enumerate(records):
            access = self._extract_accessright(instance)
            is_open = access in {"OPEN", "OA", "OPEN ACCESS"}
            for url in self._extract_instance_urls(instance):
                if not url:
                    continue
                score = match_rank * 10_000
                if is_open:
                    score += 1_000
                if self._looks_like_pdf_url(url):
                    score += 500
                ranked.append((score, match_rank, -order, 0 if is_open else 1, url, is_open))

        # De-duplicate after ranking so duplicate url/webresource fields do
        # not consume candidate slots or alter ordering.
        ranked.sort(key=lambda item: (-item[0], -item[1], item[2]))
        deduped: list[tuple[str, int, bool]] = []
        seen: set[str] = set()
        for _score, match_rank, _order, _access, url, is_open in ranked:
            if url in seen:
                continue
            seen.add(url)
            deduped.append((url, match_rank, is_open))
        return deduped

    def _extract_ranked_urls(
        self, metadata: dict[str, Any], *, doi: str | None = None
    ) -> list[tuple[str, bool]]:
        """Extract repository URLs ordered by exact PID, OA, and PDF signal."""

        return [
            (url, is_open)
            for url, _match_rank, is_open in self._extract_ranked_url_records(metadata, doi=doi)
        ]

    def _extract_urls(
        self, metadata: dict[str, Any], *, doi: str | None = None
    ) -> tuple[list[str], list[str]]:
        """Return OA and non-OA URLs in the same ranked order as the fetcher."""

        ranked = self._extract_ranked_urls(metadata, doi=doi)
        open_urls = [url for url, is_open in ranked if is_open]
        other_urls = [url for url, is_open in ranked if not is_open]
        return open_urls, other_urls

    @classmethod
    def _iter_pid_matching_nodes(cls, value: Any, doi: str) -> list[dict[str, Any]]:
        """Return descendant nodes carrying the requested PID.

        OpenAIRE's deduplicated result can put the PID on a child result,
        an ``instance`` wrapper, or the nested instance itself.  Only walk
        metadata/result/instance containers here; web-resource payloads are
        unrelated to bibliographic metadata and should not affect matching.
        """

        if isinstance(value, list):
            nodes: list[dict[str, Any]] = []
            for item in value:
                nodes.extend(cls._iter_pid_matching_nodes(item, doi))
            return nodes
        if not isinstance(value, dict):
            return []

        nodes: list[dict[str, Any]] = []
        if cls._node_matches_doi(value, doi):
            # Once an exact PID-bearing node is found, its bibliographic
            # fields may live on a nested result/instance without repeating
            # the PID.  Include that branch for field extraction.
            nodes.append(value)
            for key in ("metadata", "oaf:entity", "oaf:result", "result", "instance"):
                nodes.extend(cls._iter_descendant_nodes(value.get(key)))
            return nodes
        for key in ("metadata", "oaf:entity", "oaf:result", "result", "instance"):
            nodes.extend(cls._iter_pid_matching_nodes(value.get(key), doi))
        return nodes

    @classmethod
    def _iter_descendant_nodes(cls, value: Any) -> list[dict[str, Any]]:
        """Return metadata-bearing descendants under an exact PID branch."""

        if isinstance(value, list):
            nodes: list[dict[str, Any]] = []
            for item in value:
                nodes.extend(cls._iter_descendant_nodes(item))
            return nodes
        if not isinstance(value, dict):
            return []

        nodes = [value]
        for key in ("metadata", "oaf:entity", "oaf:result", "result", "instance"):
            nodes.extend(cls._iter_descendant_nodes(value.get(key)))
        return nodes

    @classmethod
    def _extract_title_from_node(cls, node: dict[str, Any]) -> str:
        """Extract a title directly from a result/instance metadata node."""

        for title in cls._extract_text_values(node.get("title")):
            if title.strip():
                return title.strip()
        return ""

    @classmethod
    def _extract_year_from_node(cls, node: dict[str, Any]) -> int | None:
        """Extract a publication/acceptance year from a metadata node."""

        date_value = node.get("dateofacceptance") or node.get("publicationDate")
        for date_text in cls._extract_text_values(date_value):
            match = re.search(r"(19|20)\d{2}", date_text)
            if match:
                return int(match.group(0))
        return None

    def _extract_selected_metadata(
        self, metadata: dict[str, Any], *, doi: str, match_rank: int
    ) -> tuple[str, int | None]:
        """Extract metadata associated with the URL that was selected.

        A rank-2 URL came from an exact child/instance PID.  Prefer title and
        year fields attached to that same branch, then fill missing fields
        from the deduplicated parent record.  For parent/related URLs, the
        parent remains the only safe bibliographic fallback.
        """

        parent_title = self._extract_title(metadata)
        parent_year = self._extract_year(metadata)
        if match_rank < 2:
            return parent_title, parent_year

        entity = metadata.get("oaf:entity") or {}
        result = entity.get("oaf:result") or {}
        children = result.get("children") or {}
        matching_nodes: list[dict[str, Any]] = []
        for key in ("result", "instance"):
            matching_nodes.extend(self._iter_pid_matching_nodes(children.get(key), doi))

        exact_title = ""
        exact_year: int | None = None
        for node in matching_nodes:
            if not exact_title:
                exact_title = self._extract_title_from_node(node)
            if exact_year is None:
                exact_year = self._extract_year_from_node(node)
            if exact_title and exact_year is not None:
                break

        return exact_title or parent_title, exact_year if exact_year is not None else parent_year

    @staticmethod
    def _extract_title(metadata: dict[str, Any]) -> str:
        entity = metadata.get("oaf:entity") or {}
        result = entity.get("oaf:result") or {}
        for title in OpenAireSource._extract_text_values(result.get("title")):
            if title.strip():
                return title.strip()
        return ""

    @staticmethod
    def _extract_year(metadata: dict[str, Any]) -> int | None:
        entity = metadata.get("oaf:entity") or {}
        result = entity.get("oaf:result") or {}
        date_value = result.get("dateofacceptance") or result.get("publicationDate")
        for date_text in OpenAireSource._extract_text_values(date_value):
            match = re.search(r"(19|20)\d{2}", date_text)
            if match:
                return int(match.group(0))
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
        return path.endswith(".pdf") or ".pdf" in query or "/pdf" in path or "/pdfft" in path

    @staticmethod
    def _looks_like_pdf_url(url: str) -> bool:
        if not url:
            return False
        url_lower = url.strip().lower()
        if not OpenAireSource._is_http_url(url_lower):
            return False
        if url_lower.endswith(".pdf"):
            return True
        parsed = urlparse(url_lower)
        path = parsed.path or ""
        query = parsed.query or ""
        if path.endswith(".pdf") or ".pdf" in path:
            return True
        landing_patterns = [
            "/doi.org/",
            "/abstract",
            "/article/",
            "/stable/",
            "researchgate",
        ]
        # These are known full-text endpoints whose URLs often do not end in
        # .pdf (for example PLOS's ``article/file?...type=printable`` and
        # OSTI's redirecting ``servlets/purl`` endpoint).
        if "/article/file" in path or "/servlets/purl/" in path:
            return True
        if any(pattern in url_lower for pattern in landing_patterns):
            return False
        pdf_patterns = [
            "/pdf",
            "download",
            "content/pdf",
            "/article-pdf/",
            "/pdfviewer/",
            "viewer/pdf",
        ]
        if any(pattern in url_lower for pattern in pdf_patterns):
            return True
        return any(token in query for token in ("format=pdf", "type=printable", "filetype=pdf"))

    @staticmethod
    def _derive_pdf_from_landing_url(landing_url: str | None) -> str | None:
        if not landing_url:
            return None
        candidates = derive_publisher_pdf_candidates(landing_url)
        if candidates:
            return candidates[0]
        return None

    @classmethod
    def _derive_pdf_from_landing_urls(cls, landing_urls: list[str]) -> str | None:
        for url in landing_urls:
            derived = cls._derive_pdf_from_landing_url(url)
            if derived:
                return derived
        return None
