"""
Main Sci-Hub client providing high-level interface with multi-source support.
"""

import os
import re
import time
from dataclasses import replace
from html import unescape
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

from .config.settings import settings
from .converters.pdf_to_md import PdfToMarkdownConverter
from .core.doi_processor import DOIProcessor
from .core.downloader import FileDownloader
from .core.file_manager import FileManager
from .core.mirror_manager import MirrorManager
from .core.parser import ContentParser
from .core.source_manager import SourceManager
from .models import DownloadProgress, DownloadResult, ProgressCallback
from .network.session import BasicSession
from .sources.arxiv_source import ArxivSource
from .sources.base_oai_source import BASESource
from .sources.core_source import CORESource
from .sources.direct_pdf_source import DirectPDFSource
from .sources.europe_pmc_oa_source import EuropePMCOASource
from .sources.europe_pmc_source import EuropePMCSource
from .sources.html_landing_source import HTMLLandingSource
from .sources.openaire_source import OpenAireSource
from .sources.osti_source import OSTISource
from .sources.openalex_source import OpenAlexSource
from .sources.pmc_source import PMCSource
from .sources.semantic_scholar_source import SemanticScholarSource
from .sources.scihub_source import SciHubSource
from .sources.unpaywall_source import UnpaywallSource
from .utils.logging import get_logger
from .utils.retry import RetryConfig

logger = get_logger(__name__)


class SciHubClient:
    """Main client interface with multi-source support (Sci-Hub, Unpaywall, arXiv, CORE)."""

    _ACADEMIC_HOST_HINTS = (
        "journal",
        "journals",
        "research",
        "scholar",
        "library",
        "archive",
        "repository",
        "repo",
        "eprints",
        "preprints",
        "university",
        "univ",
        "institute",
        "college",
        "faculty",
        "campus",
        "preprint",
        "arxiv",
        "academic",
        "dtu",
    )
    _ACADEMIC_ONLY_EXTRA_NON_ACADEMIC_HOST_MARKERS = (
        "rebelliongroup.com",
        "themodems.com",
        "bruceturkel.com",
        "onclusive.com",
        "evdances.com",
        "civicbrand.com",
        "theguardian.com",
        "english.stackexchange.com",
        "getflamingo.com",
        "s100.copyright.com",
        "formpl.us",
        "ichef.bbci.co.uk",
        "media.jaguarlandrover.com",
        "stockmarketwatch.com",
        "dictionary.cambridge.org",
        "scribd.com",
        "linkedin.com",
        "dokumen.pub",
        "mckinsey.com",
        "autoweek.com",
        "cdn.shopify.com",
        "hbr.org",
        "slideshare.net",
        "apnews.com",
        "caranddriver.com",
        "pinterest.com",
        "nationwidevehiclecontracts.co.uk",
        "sportsbusinessdaily.com",
        "marketresearch.com",
        "media.post.rvohealth.io",
        "historyofluxury.com",
        "whitehouse.gov",
        "marketingdive.com",
        "digitalcommerce360.com",
        "growprogress.ai",
        "angelone.in",
        "univdatos.com",
        "substack.com",
    )
    _ACADEMIC_PATH_HINTS = (
        "/doi/",
        "/article",
        "/articles/",
        "/paper",
        "/papers/",
        "/manuscript",
        "/preprint",
        "/pdf",
        "/abs/",
        "/abstract",
        "/fulltext",
        "/bitstream/",
        "/handle/",
        "/eprint/",
        "/eprints/",
        "/etd/",
        "/thesis",
        "/dissertation",
        "/conference",
        "/conferences",
        "/ojs/",
        "/dspace/",
        "/record/",
        "blobtype=pdf",
        "download=true",
    )
    _NON_ACADEMIC_PATH_HINTS = (
        "/about",
        "/about-us",
        "/account",
        "/author",
        "/authors",
        "/blog",
        "/careers",
        "/contact",
        "/events",
        "/help",
        "/home",
        "/index",
        "/jobs",
        "/login",
        "/media",
        "/news",
        "/press",
        "/privacy",
        "/search",
        "/signup",
        "/sign-up",
        "/subscribe",
        "/terms",
        "/policy",
        "/logo",
        "/image",
        "/images",
        "/gallery",
        "/thumbnail",
        "search=",
        "query=",
        "q=",
    )

    def __init__(
        self,
        output_dir: str = None,
        mirrors: list[str] = None,
        timeout: int = None,
        retries: int = None,
        email: str = None,
        mirror_manager: MirrorManager = None,
        parser: ContentParser = None,
        file_manager: FileManager = None,
        downloader: FileDownloader = None,
        source_manager: SourceManager = None,
        convert_to_md: bool = False,
        md_output_dir: str | None = None,
        md_backend: str = "pymupdf4llm",
        md_strict: bool = True,
        md_overwrite: bool = False,
        md_converter: PdfToMarkdownConverter | None = None,
        trace_html: bool = False,
        trace_html_dir: str | None = None,
        trace_html_max_chars: int = 2_000_000,
        enable_core: bool = False,
        fast_fail: bool = False,
        download_deadline_seconds: float | None = None,
        academic_only: bool = False,
    ):
        """Initialize client with optional dependency injection."""

        # Configuration
        self.output_dir = output_dir or settings.output_dir
        self.timeout = timeout or settings.timeout
        self.retry_config = RetryConfig(max_attempts=retries or settings.retries)
        self.email = email or settings.email

        self.convert_to_md = convert_to_md
        self.md_output_dir = md_output_dir
        self.md_backend = md_backend
        self.md_strict = md_strict
        self.md_overwrite = md_overwrite
        self.md_converter = md_converter
        self.trace_html = trace_html
        self.trace_html_dir = trace_html_dir
        self.trace_html_max_chars = trace_html_max_chars
        self.enable_core = enable_core
        self.fast_fail = fast_fail
        self.download_deadline_seconds = download_deadline_seconds
        self.academic_only = academic_only
        self._pii_doi_cache: dict[str, str | None] = {}

        # Dependency injection with defaults
        self.mirror_manager = mirror_manager or MirrorManager(mirrors, self.timeout)
        self.parser = parser or ContentParser()
        self.file_manager = file_manager or FileManager(self.output_dir)
        self.downloader = downloader or FileDownloader(
            BasicSession(self.timeout),
            timeout=self.timeout,
            fast_fail=self.fast_fail,
            retries=retries,
            download_deadline_seconds=self.download_deadline_seconds,
        )

        # DOI processor (stateless)
        self.doi_processor = DOIProcessor()

        # Multi-source support
        if source_manager is None:
            # Initialize paper sources
            sources = [
                SciHubSource(
                    mirror_manager=self.mirror_manager,
                    parser=self.parser,
                    doi_processor=self.doi_processor,
                    downloader=self.downloader,
                )
            ]

            # Direct URL sources: enable direct PDF and PMC handling for URL inputs
            sources.insert(0, HTMLLandingSource(downloader=self.downloader))
            sources.insert(0, PMCSource(downloader=self.downloader))
            sources.insert(0, DirectPDFSource())

            # arXiv: Free and open, always enabled (high priority for preprints)
            sources.insert(0, ArxivSource(timeout=self.timeout))

            # OSTI: DOE technical report DOIs (10.2172)
            sources.insert(0, OSTISource())

            # OpenAlex: OA metadata + PDF links, no email required
            sources.insert(
                0,
                OpenAlexSource(
                    timeout=self.timeout,
                    email=self.email,
                    api_key=settings.openalex_api_key,
                    fast_fail=self.fast_fail,
                ),
            )

            # Semantic Scholar: OA metadata + PDF links, no email required
            sources.insert(
                0,
                SemanticScholarSource(timeout=self.timeout, fast_fail=self.fast_fail),
            )

            # OpenAIRE: OA repository links, no email required
            sources.insert(
                0,
                OpenAireSource(timeout=self.timeout, fast_fail=self.fast_fail),
            )

            # Europe PMC: OA discovery for biomedical literature (no email required)
            sources.insert(
                0,
                EuropePMCSource(timeout=self.timeout, fast_fail=self.fast_fail),
            )
            sources.insert(
                0,
                EuropePMCOASource(timeout=self.timeout, fast_fail=self.fast_fail),
            )

            # Only enable Unpaywall when email is provided
            if self.email:
                sources.insert(
                    0,
                    UnpaywallSource(
                        email=self.email, timeout=self.timeout, fast_fail=self.fast_fail
                    ),
                )

            # BASE OAI-PMH: OA repository links (IP-restricted interface)
            sources.insert(0, BASESource(timeout=self.timeout, fast_fail=self.fast_fail))

            # CORE does not require email, keep as OA fallback (unless explicitly disabled)
            if self.enable_core:
                sources.append(CORESource(api_key=settings.core_api_key, timeout=self.timeout))
            else:
                logger.info("CORE source disabled by configuration")

            self.source_manager = SourceManager(
                sources=sources,
                year_threshold=settings.year_threshold,
                enable_year_routing=settings.enable_year_routing,
            )
        else:
            self.source_manager = source_manager

    def download_paper(
        self, identifier: str, progress_callback: Optional[ProgressCallback] = None
    ) -> DownloadResult:
        """
        Download a paper given its DOI or URL.

        Uses fine-grained retry at lower layers (download, API calls).
        No coarse-grained retry at this level.
        """
        try:
            cleaned_identifier = self._extract_identifier_from_line(identifier)
            if cleaned_identifier:
                identifier = cleaned_identifier

            doi = self.doi_processor.normalize_doi(identifier)
            logger.info(f"Downloading paper: {doi}")

            if self.fast_fail and self._should_fast_fail_url(identifier, doi):
                error = "Fast-fail: non-academic or non-document URL"
                logger.error(error)
                return DownloadResult(
                    identifier=identifier,
                    normalized_identifier=doi,
                    success=False,
                    error=error,
                )

            return self._download_single_paper(
                identifier=identifier,
                normalized_identifier=doi,
                progress_callback=progress_callback,
            )
        except Exception as e:
            logger.error(f"Download failed for {identifier}: {e}")
            return DownloadResult(
                identifier=identifier,
                normalized_identifier=identifier,
                success=False,
                error=str(e),
            )

    def _download_single_paper(
        self,
        identifier: str,
        normalized_identifier: str,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> DownloadResult:
        """
        Single download attempt using multi-source manager.

        Gets URL and metadata in one pass to avoid duplicate API calls.
        """
        start_time = time.time()
        html_events: list[dict[str, Any]] = []
        if normalized_identifier.startswith("http") and "sciencedirect.com" in normalized_identifier.lower():
            try:
                resolved = self._resolve_sciencedirect_pii_to_doi(normalized_identifier)
            except Exception as e:
                logger.debug(f"Failed to resolve ScienceDirect PII: {e}")
                resolved = None
            if resolved:
                logger.info(f"Resolved ScienceDirect PII to DOI: {resolved}")
                normalized_identifier = resolved

        def _build_result(
            *,
            success: bool,
            file_path: Optional[str] = None,
            file_size: Optional[int] = None,
            metadata: Optional[dict] = None,
            source: Optional[str] = None,
            download_url: Optional[str] = None,
            error: Optional[str] = None,
            md_path: str | None = None,
            md_success: bool | None = None,
            md_error: str | None = None,
            source_attempts: list[dict[str, Any]] | None = None,
            html_snapshots: list[dict[str, Any]] | None = None,
        ) -> DownloadResult:
            title = metadata.get("title") if isinstance(metadata, dict) else None
            year = metadata.get("year") if isinstance(metadata, dict) else None
            return DownloadResult(
                identifier=identifier,
                normalized_identifier=normalized_identifier,
                success=success,
                file_path=file_path,
                file_size=file_size,
                source=source,
                metadata=metadata,
                title=title,
                year=year,
                download_url=download_url,
                download_time=time.time() - start_time,
                error=error,
                md_path=md_path,
                md_success=md_success,
                md_error=md_error,
                source_attempts=source_attempts,
                html_snapshots=html_snapshots,
            )

        def _collect_html_snapshot(snapshot: dict[str, Any]) -> None:
            if self.trace_html:
                html_events.append(dict(snapshot))

        source_attempts: list[dict[str, Any]]
        # Get PDF URL and metadata together (avoids duplicate API calls)
        if hasattr(self.source_manager, "get_pdf_url_with_metadata_and_trace"):
            download_url, metadata, source, source_attempts = (
                self.source_manager.get_pdf_url_with_metadata_and_trace(
                    normalized_identifier,
                    html_snapshot_callback=_collect_html_snapshot if self.trace_html else None,
                )
            )
        else:
            download_url, metadata, source = self.source_manager.get_pdf_url_with_metadata(
                normalized_identifier
            )
            source_attempts = []

        if not download_url:
            error = f"Could not find PDF URL for {normalized_identifier} from any source"
            logger.error(error)
            return _build_result(
                success=False,
                metadata=metadata,
                source=source,
                error=error,
                source_attempts=source_attempts,
                html_snapshots=self._persist_html_snapshots(identifier, html_events),
            )

        progress_state = {"bytes": 0, "total": None}
        active_download_url = {"url": download_url}

        def _handle_progress(bytes_downloaded: int, total_bytes: Optional[int]) -> None:
            progress_state["bytes"] = bytes_downloaded
            progress_state["total"] = total_bytes
            if progress_callback:
                progress_callback(
                    DownloadProgress(
                        identifier=identifier,
                        url=active_download_url["url"],
                        bytes_downloaded=bytes_downloaded,
                        total_bytes=total_bytes,
                        done=False,
                    )
                )

        # Download the PDF (with automatic retry at download layer)
        success = False
        error_msg: str | None = None
        attempted_errors: list[tuple[str, str]] = []

        attempted_sources: set[str] = set()
        max_fallback_rounds = 1
        fallback_round = 0

        while True:
            download_candidates = self._collect_download_candidates(
                primary_url=download_url,
                source=source,
                metadata=metadata,
                source_attempts=source_attempts,
            )
            if not download_candidates:
                error = f"No valid download URL candidates for {normalized_identifier}"
                logger.error(error)
                return _build_result(
                    success=False,
                    metadata=metadata,
                    source=source,
                    download_url=download_url,
                    error=error,
                    source_attempts=source_attempts,
                    html_snapshots=self._persist_html_snapshots(identifier, html_events),
                )
            logger.debug(
                f"Download URL candidates ({len(download_candidates)}): {download_candidates}"
            )

            # Generate filename from metadata if available
            filename = self._generate_filename(normalized_identifier, metadata)
            output_path = self.file_manager.get_output_path(filename)

            attempted_errors.clear()
            success = False
            error_msg = None
            active_download_url["url"] = download_candidates[0]

            for index, candidate_url in enumerate(download_candidates, start=1):
                active_download_url["url"] = candidate_url
                logger.info(
                    f"Downloading via candidate URL ({index}/{len(download_candidates)}): {candidate_url}"
                )
                push_trace = getattr(self.downloader, "push_trace_context", None)
                clear_trace = getattr(self.downloader, "clear_trace_context", None)
                use_download_trace = self.trace_html and callable(push_trace) and callable(clear_trace)

                if use_download_trace:
                    push_trace(
                        {
                            "identifier": normalized_identifier,
                            "source": source or "unknown_source",
                            "phase": "download",
                            "candidate_index": index,
                            "candidate_total": len(download_candidates),
                        },
                        html_snapshot_callback=_collect_html_snapshot,
                    )
                try:
                    try:
                        success, error_msg = self.downloader.download_file(
                            candidate_url,
                            output_path,
                            progress_callback=_handle_progress if progress_callback else None,
                        )
                    except Exception as e:
                        success = False
                        error_msg = str(e)
                        logger.warning(
                            "Download failed for candidate URL %s: %s", candidate_url, e
                        )
                finally:
                    if use_download_trace:
                        clear_trace()
                if success:
                    if self.file_manager.validate_file(output_path):
                        download_url = candidate_url
                        break

                    error_msg = "Downloaded file validation failed"
                    logger.error(error_msg)
                    if os.path.exists(output_path):
                        os.unlink(output_path)
                    success = False

                if "sci-hub" in candidate_url.lower():
                    logger.warning("Sci-Hub download failed, invalidating mirror cache")
                    scihub = [
                        s for s in self.source_manager.sources.values() if s.name == "Sci-Hub"
                    ]
                    if scihub:
                        scihub[0].mirror_manager.invalidate_cache()

                attempted_errors.append((candidate_url, error_msg or "Download failed"))

            if success:
                break

            if (
                fallback_round >= max_fallback_rounds
                or not self.fast_fail
                or not self._should_retry_sources_after_download_failure(error_msg or "")
            ):
                break

            retry_identifier = self._select_retry_identifier(normalized_identifier, metadata)
            if not self._is_retryable_identifier(retry_identifier):
                break

            if source:
                attempted_sources.add(source)

            fallback_round += 1
            logger.info(
                f"Retrying sources after download failure (round {fallback_round}/{max_fallback_rounds})"
            )
            download_url, metadata, source, retry_attempts = (
                self.source_manager.get_pdf_url_with_metadata_and_trace(
                    retry_identifier,
                    html_snapshot_callback=_collect_html_snapshot if self.trace_html else None,
                    exclude_sources=attempted_sources if attempted_sources else None,
                    force_sequential=True,
                )
            )
            if not download_url:
                break
            if retry_attempts:
                if source_attempts:
                    source_attempts.extend(retry_attempts)
                else:
                    source_attempts = retry_attempts

        if progress_callback:
            progress_callback(
                DownloadProgress(
                    identifier=identifier,
                    url=active_download_url["url"],
                    bytes_downloaded=progress_state["bytes"],
                    total_bytes=progress_state["total"],
                    done=True,
                )
            )
        if not success:
            error_msg = error_msg or "Download failed"
            if len(attempted_errors) > 1:
                details = "; ".join(f"{url} => {reason}" for url, reason in attempted_errors)
                error_msg = f"{error_msg}. Tried {len(attempted_errors)} candidate URLs: {details}"
            logger.error(f"Failed to download {normalized_identifier}: {error_msg}")
            return _build_result(
                success=False,
                metadata=metadata,
                source=source,
                download_url=active_download_url["url"],
                error=error_msg,
                source_attempts=source_attempts,
                html_snapshots=self._persist_html_snapshots(identifier, html_events),
            )

        md_path: str | None = None
        md_success: bool | None = None
        md_error: str | None = None
        if self.convert_to_md:
            try:
                md_path, md_success, md_error = self._convert_pdf_to_markdown(output_path)
            except Exception as e:
                md_success = False
                md_error = str(e)

        file_size = os.path.getsize(output_path)
        logger.info(f"Successfully downloaded {normalized_identifier} ({file_size} bytes)")
        return _build_result(
            success=True,
            file_path=output_path,
            file_size=file_size,
            metadata=metadata,
            source=source,
            download_url=download_url,
            md_path=md_path,
            md_success=md_success,
            md_error=md_error,
            source_attempts=source_attempts,
        )

    def _persist_html_snapshots(
        self, identifier: str, snapshots: list[dict[str, Any]]
    ) -> list[dict[str, Any]] | None:
        """
        Persist captured HTML snapshots to disk and return metadata records.

        Snapshots are only persisted when trace_html is enabled.
        """
        if not self.trace_html or not snapshots:
            return None

        base_dir = (
            Path(self.trace_html_dir)
            if self.trace_html_dir
            else Path(self.output_dir) / "trace-html"
        )
        identifier_dir = base_dir / self._safe_trace_token(identifier)
        identifier_dir.mkdir(parents=True, exist_ok=True)

        saved_records: list[dict[str, Any]] = []
        for index, snapshot in enumerate(snapshots, start=1):
            record = {k: v for k, v in snapshot.items() if k != "html"}

            raw_html = snapshot.get("html")
            html_text = raw_html if isinstance(raw_html, str) else None
            record["html_chars"] = len(html_text) if html_text is not None else 0

            status_part = str(
                snapshot.get("status_code") if snapshot.get("status_code") is not None else "na"
            )
            source_part = self._safe_trace_token(str(snapshot.get("source") or "unknown_source"))
            fetcher_part = self._safe_trace_token(str(snapshot.get("fetcher") or "requests"))

            if not html_text:
                record["file_path"] = None
                saved_records.append(record)
                continue

            truncated = False
            if len(html_text) > self.trace_html_max_chars:
                html_text = html_text[: self.trace_html_max_chars]
                truncated = True

            record["truncated"] = truncated
            target = identifier_dir / f"{index:03d}_{source_part}_{fetcher_part}_{status_part}.html"
            try:
                target.write_text(html_text, encoding="utf-8", errors="ignore")
                record["file_path"] = str(target)
            except Exception as e:
                record["file_path"] = None
                record["snapshot_error"] = str(e)

            saved_records.append(record)

        return saved_records

    @staticmethod
    def _safe_trace_token(value: str) -> str:
        cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("._-")
        if not cleaned:
            return "unknown"
        return cleaned[:120]

    def _collect_download_candidates(
        self,
        *,
        primary_url: str,
        source: str | None,
        metadata: dict[str, Any] | None,
        source_attempts: list[dict[str, Any]] | None = None,
    ) -> list[str]:
        """
        Collect candidate URLs for final file download.

        For CORE results, try additional metadata URLs when the primary URL fails.
        """
        seen: set[str] = set()
        candidates: list[str] = []

        def _add(candidate: Any) -> None:
            if not isinstance(candidate, str):
                return
            cleaned = self._normalize_download_candidate(candidate)
            if not cleaned or cleaned in seen:
                return
            seen.add(cleaned)
            candidates.append(cleaned)

        _add(primary_url)
        if isinstance(metadata, dict):
            _add(metadata.get("pdf_url"))
        if source_attempts:
            for attempt in source_attempts:
                if not isinstance(attempt, dict):
                    continue
                candidate = attempt.get("pdf_url")
                _add(candidate)

        if source == "CORE" and isinstance(metadata, dict):
            for key in ("source_fulltext_urls", "links_download_urls"):
                values = metadata.get(key)
                if isinstance(values, list):
                    for value in values:
                        _add(value)
            links = metadata.get("links")
            if isinstance(links, list):
                for item in links:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("type", "")).lower() != "download":
                        continue
                    _add(item.get("url"))
            _add(metadata.get("core_download_url"))
        for candidate in self._derive_pmc_fallback_download_candidates(
            primary_url=primary_url,
            source=source,
            fast_fail=self.fast_fail,
        ):
            _add(candidate)

        return candidates

    @staticmethod
    def _normalize_download_candidate(candidate: str) -> str | None:
        cleaned = unescape(candidate.strip())
        if not cleaned:
            return None

        def _sanitize(url: str) -> str:
            trimmed = re.split(r"\)\]\(https?://", url, maxsplit=1)[0]
            trimmed = re.split(r"\]\(https?://", trimmed, maxsplit=1)[0]
            return trimmed.rstrip(")}],;")

        # Keep the most plausible URL token when inputs contain markdown/link concatenation.
        urls = re.findall(r"https?://[^\s\"'<>]+", cleaned)
        if urls:
            cleaned = _sanitize(
                next(
                    (
                        url
                        for url in urls
                        if ".pdf" in url.lower()
                        or "/pdf" in url.lower()
                        or "/download/" in url.lower()
                        or "blobtype=pdf" in url.lower()
                    ),
                    urls[0],
                )
            )
        else:
            cleaned = _sanitize(cleaned)
        try:
            parsed = urlparse(cleaned)
        except ValueError:
            return None
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        return cleaned

    @staticmethod
    def _derive_pmc_fallback_download_candidates(
        *, primary_url: str, source: str | None, fast_fail: bool = False
    ) -> list[str]:
        """
        Derive alternate PMC download endpoints for challenge-prone PMC PDF links.
        """
        try:
            parsed = urlparse(primary_url.strip())
        except ValueError:
            return []
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return []

        host = parsed.netloc.lower()
        source_name = (source or "").strip().lower()
        if (
            source_name not in {"pmc", "europe pmc", "europe pmc oa"}
            and "pmc.ncbi.nlm.nih.gov" not in host
            and "ncbi.nlm.nih.gov" not in host
            and "europepmc.org" not in host
        ):
            return []

        match = re.search(r"(PMC\d+)", primary_url, re.IGNORECASE)
        if not match:
            return []
        pmc_id = match.group(1).upper()

        candidates = [
            f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/pdf/",
            f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/pdf/",
            f"https://europepmc.org/articles/{pmc_id}?pdf=render",
            f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmc_id}&blobtype=pdf",
        ]
        if fast_fail:
            return candidates[:2]
        return candidates

    def _convert_pdf_to_markdown(self, pdf_path: str) -> tuple[str | None, bool | None, str | None]:
        from .converters.pdf_to_md import MarkdownConvertOptions

        pdf = Path(pdf_path)
        output_dir = Path(self.md_output_dir) if self.md_output_dir else pdf.parent / "md"
        md_path = output_dir / f"{pdf.stem}.md"
        output_dir.mkdir(parents=True, exist_ok=True)

        if md_path.exists() and not self.md_overwrite:
            return str(md_path), True, None

        backend = (self.md_backend or "pymupdf4llm").lower().strip()
        converter = self.md_converter
        if converter is None:
            if backend != "pymupdf4llm":
                return str(md_path), False, f"Unsupported markdown backend: {self.md_backend}"
            from .converters.pymupdf4llm_converter import Pymupdf4llmConverter

            converter = Pymupdf4llmConverter()

        ok, error = converter.convert(
            str(pdf),
            str(md_path),
            options=MarkdownConvertOptions(overwrite=self.md_overwrite),
        )
        if not ok:
            return str(md_path), False, error or "Markdown conversion failed"
        return str(md_path), True, None

    def _generate_filename(self, doi: str, metadata: Optional[dict]) -> str:
        """
        Generate filename from metadata or DOI.

        Args:
            doi: The DOI
            metadata: Optional metadata dict from source

        Returns:
            Generated filename
        """
        if metadata and metadata.get("title"):
            try:
                from .metadata_utils import generate_filename_from_metadata

                return generate_filename_from_metadata(
                    metadata.get("title", ""), metadata.get("year", ""), doi
                )
            except Exception as e:
                logger.debug(f"Could not generate filename from metadata: {e}")

        # If the identifier is a URL (e.g., direct PDF link), use URL-based naming.
        parsed = urlparse(doi)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return self.file_manager.generate_filename_from_url(doi)

        # Fallback to DOI-based filename
        return self.file_manager.generate_filename(doi, html_content=None)

    def download_from_file(
        self,
        input_file: str,
        parallel: int = None,
        progress_callback: Optional[ProgressCallback] = None,
    ) -> list[DownloadResult]:
        """Download papers from a file containing DOIs or URLs."""
        parallel = parallel or settings.parallel
        parallel = max(1, parallel)

        # Read input file
        try:
            with open(input_file, encoding="utf-8") as f:
                lines = f.readlines()
        except Exception as e:
            logger.error(f"Error reading input file: {e}")
            return []

        # Filter out comments and empty lines, and extract clean identifiers.
        extracted_entries: list[tuple[str, str]] = []
        for line in lines:
            raw_line = (line or "").strip()
            if not raw_line or raw_line.startswith("#"):
                continue
            extracted = self._extract_identifier_from_line(raw_line)
            if not extracted:
                continue
            extracted_entries.append((raw_line, extracted))

        raw_identifiers = [entry[1] for entry in extracted_entries]
        if self.academic_only:
            total_before_filter = len(extracted_entries)
            def _should_keep(entry: tuple[str, str]) -> bool:
                original, identifier = entry
                if not self._is_probably_academic_identifier(identifier):
                    return False
                if self.fast_fail and self._should_fast_fail_url(identifier, identifier):
                    return False
                return True
            extracted_entries = [
                (original, identifier)
                for original, identifier in extracted_entries
                if _should_keep((original, identifier))
            ]
            dropped = total_before_filter - len(extracted_entries)
            logger.info(
                "Academic-only filter enabled: kept %s/%s identifiers (dropped %s non-academic or non-document URLs)",
                len(extracted_entries),
                total_before_filter,
                dropped,
            )
            raw_identifiers = [entry[1] for entry in extracted_entries]

        normalized_groups: dict[str, list[tuple[int, str, str, str]]] = {}
        for index, (original_identifier, identifier) in enumerate(extracted_entries):
            normalized = self.doi_processor.normalize_doi(identifier)
            normalized_groups.setdefault(normalized, []).append(
                (index, original_identifier, identifier, normalized)
            )

        tasks: list[tuple[str, str, list[tuple[int, str, str, str]]]] = []
        for dedupe_key, entries in normalized_groups.items():
            variants = [cleaned_identifier for _, _original, cleaned_identifier, _normalized in entries]
            representative = self._select_best_identifier_variant(variants)
            tasks.append((dedupe_key, representative, entries))

        logger.info(
            "Found %s papers to download (%s unique after normalization)",
            len(extracted_entries),
            len(tasks),
        )

        unique_results: list[Optional[DownloadResult]] = [None] * len(tasks)

        if parallel == 1 or len(tasks) <= 1:
            for i, (_normalized, identifier, _entries) in enumerate(tasks):
                logger.info(f"Processing {i + 1}/{len(tasks)}: {identifier}")
                unique_results[i] = self.download_paper(
                    identifier, progress_callback=progress_callback
                )

                # Add a small delay between sequential downloads
                if i < len(tasks) - 1:
                    time.sleep(2)
        else:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            workers = min(parallel, len(tasks))
            logger.info(f"Downloading {len(tasks)} unique papers with {workers} workers")

            def _download_one(index: int, identifier: str) -> tuple[int, DownloadResult]:
                return index, self.download_paper(identifier, progress_callback=progress_callback)

            with ThreadPoolExecutor(max_workers=workers) as executor:
                future_to_index = {
                    executor.submit(_download_one, index, identifier): index
                    for index, (_normalized, identifier, _entries) in enumerate(tasks)
                }
                for future in as_completed(future_to_index):
                    index, result = future.result()
                    unique_results[index] = result

        results: list[Optional[DownloadResult]] = [None] * len(raw_identifiers)
        for task_index, (_dedupe_key, _representative, entries) in enumerate(tasks):
            base_result = unique_results[task_index]
            if base_result is None:
                continue
            for original_index, original_identifier, _cleaned_identifier, original_normalized in entries:
                results[original_index] = replace(
                    base_result,
                    identifier=original_identifier,
                    normalized_identifier=original_normalized,
                )

        results = [result for result in results if result is not None]

        successful = sum(1 for result in results if result.success)
        logger.info(f"Downloaded {successful}/{len(raw_identifiers)} papers")

        return results

    @staticmethod
    def _is_probably_academic_identifier(identifier: str) -> bool:
        token = (identifier or "").strip()
        if not token:
            return False
        lowered = token.lower()

        # DOI and arXiv identifiers should always be considered academic.
        if lowered.startswith("10.") or lowered.startswith("arxiv:"):
            return True

        parsed = urlparse(token)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            # Keep unknown non-URL identifiers to avoid dropping valid academic tokens.
            return True

        host = parsed.netloc.lower()
        if FileDownloader._is_obvious_non_academic_host(host):
            return False
        if host.startswith("www."):
            host = host[4:]
        if any(
            marker in host for marker in SciHubClient._ACADEMIC_ONLY_EXTRA_NON_ACADEMIC_HOST_MARKERS
        ):
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
        if any(hint in path_query for hint in SciHubClient._NON_ACADEMIC_PATH_HINTS):
            return False

        if host.endswith(".edu") or host.endswith(".gov") or ".ac." in host:
            return True
        if any(marker in host for marker in FileDownloader._ACADEMIC_HOST_MARKERS):
            return True
        if any(hint in host for hint in SciHubClient._ACADEMIC_HOST_HINTS):
            return True

        if any(hint in path_query for hint in SciHubClient._ACADEMIC_PATH_HINTS):
            return True
        if re.search(r"10\\.[0-9]{4,9}/[-._;()/:a-z0-9]+", path_query, flags=re.I):
            return True

        # Unknown hosts without academic signals are treated as non-academic when
        # academic-only filtering is enabled.
        return False

    @staticmethod
    def _extract_identifier_from_line(line: str) -> str | None:
        if not line:
            return None

        cleaned = line.strip()
        if not cleaned:
            return None

        # Handle tab-delimited logs: take the last non-empty field.
        if "\t" in cleaned:
            parts = [part.strip() for part in cleaned.split("\t") if part.strip()]
            if parts:
                cleaned = parts[-1]

        # Drop trailing status markers like "[failed:2]" or "[success:1]".
        cleaned = re.sub(r"\s*\[[^\]]+\]\s*$", "", cleaned).strip()

        # Handle space-delimited status tokens (e.g., "... success <doi>").
        tokens = cleaned.split()
        if len(tokens) >= 3 and tokens[-2].lower() in {"success", "failed", "skipped"}:
            cleaned = tokens[-1]

        # Prefer explicit PDF URLs when present.
        pdf_url_match = re.search(r"https?://[^\s\"'<>]+?\.pdf(?:\?[^\s\"'<>]+)?", cleaned)
        if pdf_url_match:
            cleaned = pdf_url_match.group(0)
        else:
            # Prefer DOI tokens when embedded in noisy lines.
            doi_match = re.search(DOIProcessor.DOI_PATTERN, cleaned, flags=re.IGNORECASE)
            if doi_match:
                cleaned = DOIProcessor._clean_doi_candidate(doi_match.group(0))
            else:
                # arXiv identifiers commonly appear without scheme.
                arxiv_match = re.search(r"\b\d{4}\.\d{4,5}(?:v\d+)?\b", cleaned)
                if arxiv_match:
                    cleaned = arxiv_match.group(0)
                else:
                    # If a URL is embedded in the line, prefer the first URL token.
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

    @staticmethod
    def _should_fast_fail_url(identifier: str, normalized_identifier: str) -> bool:
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

    @staticmethod
    def _should_retry_sources_after_download_failure(error_msg: str) -> bool:
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

    @staticmethod
    def _is_retryable_identifier(identifier: str) -> bool:
        if not identifier:
            return False
        lowered = identifier.lower()
        if lowered.startswith("10."):
            return True
        if lowered.startswith("arxiv:"):
            return True
        # arXiv bare identifiers
        if re.fullmatch(r"\d{4}\.\d{4,5}(?:v\d+)?", identifier):
            return True
        return False

    @staticmethod
    def _select_retry_identifier(
        normalized_identifier: str, metadata: dict[str, Any] | None
    ) -> str:
        if isinstance(metadata, dict):
            for key in ("doi", "DOI"):
                value = metadata.get(key)
                if isinstance(value, str) and value.startswith("10."):
                    return value.strip()
        return normalized_identifier

    def _resolve_sciencedirect_pii_to_doi(self, identifier: str) -> str | None:
        parsed = urlparse(identifier or "")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return None
        host = parsed.netloc.lower()
        if "sciencedirect.com" not in host:
            return None

        pii_match = re.search(r"/pii/([A-Z0-9]+)", parsed.path, flags=re.I)
        if not pii_match:
            return None
        pii = pii_match.group(1).upper()
        if pii in self._pii_doi_cache:
            return self._pii_doi_cache[pii]

        try:
            params = {"filter": f"alternative-id:{pii}", "rows": 1}
            headers = {}
            if self.email:
                headers["User-Agent"] = f"scihub-cli/1.0 (mailto:{self.email})"
            response = self.downloader.session.get(
                "https://api.crossref.org/works",
                params=params,
                headers=headers,
                timeout=min(5, self.timeout),
            )
            if response.status_code == 429:
                logger.info("[Crossref] Rate limited during PII resolve; skipping cache")
                return None
            if response.status_code != 200:
                self._pii_doi_cache[pii] = None
                return None
            payload = response.json()
            items = (payload.get("message") or {}).get("items") or []
            if not items:
                self._pii_doi_cache[pii] = None
                return None
            doi = items[0].get("DOI") if isinstance(items[0], dict) else None
            if not isinstance(doi, str):
                self._pii_doi_cache[pii] = None
                return None
            doi = DOIProcessor._clean_doi_candidate(doi)
            if DOIProcessor._is_valid_doi(doi):
                self._pii_doi_cache[pii] = doi
                return doi
        except Exception as e:
            logger.debug(f"Failed to resolve PII via Crossref: {e}")

        self._pii_doi_cache[pii] = None
        return None

    @staticmethod
    def _select_best_identifier_variant(variants: list[str]) -> str:
        """
        Prefer cleaner identifier variants when multiple raw links normalize to the same key.
        """

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
