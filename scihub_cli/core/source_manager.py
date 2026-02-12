"""
Multi-source manager with intelligent routing and parallel querying.
"""

import contextlib
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Optional
from urllib.parse import urlparse

from ..sources.base import PaperSource
from ..utils.logging import get_logger

logger = get_logger(__name__)

SourceAttempt = dict[str, Any]
HtmlSnapshotCallback = Callable[[dict[str, Any]], None]

# Configuration for parallel source queries
PARALLEL_QUERY_WORKERS = 4  # Max concurrent source queries
PARALLEL_QUERY_ENABLED = True  # Can be disabled for debugging
SLOW_SOURCES = {"Sci-Hub"}


class SourceManager:
    """Manages multiple paper sources with intelligent routing based on publication year."""

    def __init__(
        self,
        sources: list[PaperSource],
        year_threshold: int = 2021,
        enable_year_routing: bool = True,
    ):
        """
        Initialize source manager.

        Args:
            sources: List of paper sources (order matters for fallback)
            year_threshold: Year threshold for routing strategy (default 2021)
            enable_year_routing: Enable intelligent year-based routing
        """
        self.sources = {source.name: source for source in sources}
        self.year_threshold = year_threshold
        self.enable_year_routing = enable_year_routing

        # Lazy-loaded year detector (only created when needed)
        self._year_detector = None

    @property
    def year_detector(self):
        """Lazy-load YearDetector only when needed."""
        if self._year_detector is None:
            from .year_detector import YearDetector

            self._year_detector = YearDetector()
        return self._year_detector

    def get_source_chain(self, doi: str, year: Optional[int] = None) -> list[PaperSource]:
        """
        Get the optimal source chain for a given identifier based on publication year.

        Strategy:
        - URLs: Direct PDF -> PMC -> HTML Landing (URL-specific handlers)
        - arXiv identifiers: arXiv first (direct match)
        - Papers before 2021: OA sources first, Sci-Hub fallback for coverage
        - Papers 2021+: OA sources only (skip Sci-Hub)
        - Unknown year: OA sources first with Sci-Hub fallback

        Args:
            doi: The DOI or identifier to route
            year: Publication year (will be detected if not provided)

        Returns:
            Ordered list of sources to try
        """
        # Check if it's an arXiv identifier - prioritize arXiv source
        if "arXiv" in self.sources and self.sources["arXiv"].can_handle(doi):
            logger.info(
                "[Router] Detected arXiv identifier, using arXiv -> Unpaywall -> CORE -> Sci-Hub"
            )
            return self._build_chain(["arXiv", "Unpaywall", "CORE", "Sci-Hub"])

        # If the input is a URL, prefer URL-specific handlers first.
        parsed = urlparse(doi)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            logger.info("[Router] Detected URL input, using Direct PDF -> PMC -> HTML Landing")
            return self._build_chain(["Direct PDF", "PMC", "HTML Landing"])

        # Detect year if not provided and routing is enabled (Crossref only supports DOIs)
        if year is None and self.enable_year_routing and doi.startswith("10."):
            year = self._get_year_smart(doi)

        # Build source chain based on year
        if year is None:
            # Unknown year: conservative strategy (OA first with Sci-Hub fallback)
            logger.info(
                f"[Router] Year unknown for {doi}, using Unpaywall -> arXiv -> CORE -> Sci-Hub"
            )
            chain = self._build_chain(["Unpaywall", "arXiv", "CORE", "Sci-Hub"])

        elif year < self.year_threshold:
            # Old papers: OA first for speed, Sci-Hub fallback for coverage
            logger.info(
                f"[Router] Year {year} < {self.year_threshold}, using Unpaywall -> arXiv -> CORE -> Sci-Hub"
            )
            chain = self._build_chain(["Unpaywall", "arXiv", "CORE", "Sci-Hub"])

        else:
            # New papers: Sci-Hub has no coverage, OA only
            logger.info(
                f"[Router] Year {year} >= {self.year_threshold}, using Unpaywall -> arXiv -> CORE"
            )
            chain = self._build_chain(["Unpaywall", "arXiv", "CORE"])

        return chain

    def _build_chain(self, source_names: list[str]) -> list[PaperSource]:
        """
        Build a source chain from source names.

        Args:
            source_names: Ordered list of source names

        Returns:
            List of source instances
        """
        chain = []
        for name in source_names:
            if name in self.sources:
                chain.append(self.sources[name])
            else:
                logger.warning(f"[Router] Source '{name}' not available, skipping")
        return chain

    def get_pdf_url(self, doi: str, year: Optional[int] = None) -> Optional[str]:
        """
        Get PDF URL trying sources in optimal order.

        Args:
            doi: The DOI to look up
            year: Publication year (optional, will be detected)

        Returns:
            PDF URL if found, None otherwise
        """
        pdf_url, _metadata, _source = self.get_pdf_url_with_metadata(doi, year)
        return pdf_url

    def get_pdf_url_with_metadata(
        self, doi: str, year: Optional[int] = None
    ) -> tuple[Optional[str], Optional[dict], Optional[str]]:
        """
        Get PDF URL and metadata in one pass (avoids duplicate API calls).

        Uses parallel querying when enabled for faster results.

        Args:
            doi: The DOI to look up
            year: Publication year (optional, will be detected)

        Returns:
            Tuple of (pdf_url, metadata, source) - all can be None
        """
        pdf_url, metadata, source, _attempts = self.get_pdf_url_with_metadata_and_trace(doi, year)
        return pdf_url, metadata, source

    def get_pdf_url_with_metadata_and_trace(
        self,
        doi: str,
        year: Optional[int] = None,
        html_snapshot_callback: HtmlSnapshotCallback | None = None,
    ) -> tuple[Optional[str], Optional[dict], Optional[str], list[SourceAttempt]]:
        """
        Get PDF URL/metadata and source-attempt trace in one pass.

        Args:
            doi: The DOI to look up
            year: Publication year (optional, will be detected)
            html_snapshot_callback: Optional callback for HTML page snapshots

        Returns:
            Tuple of (pdf_url, metadata, source, source_attempts)
        """
        chain = self.get_source_chain(doi, year)

        if PARALLEL_QUERY_ENABLED and len(chain) > 1:
            return self._query_sources_fast_then_slow(
                doi,
                chain,
                html_snapshot_callback=html_snapshot_callback,
            )
        return self._query_sources_sequential(
            doi,
            chain,
            phase="sequential",
            html_snapshot_callback=html_snapshot_callback,
        )

    def _query_sources_fast_then_slow(
        self,
        doi: str,
        chain: list[PaperSource],
        *,
        html_snapshot_callback: HtmlSnapshotCallback | None = None,
    ) -> tuple[Optional[str], Optional[dict], Optional[str], list[SourceAttempt]]:
        """
        Query fast sources in parallel first, then fall back to slow sources sequentially.

        This avoids slow providers delaying successful results from faster sources.
        """
        fast_chain = [source for source in chain if source.name not in SLOW_SOURCES]
        slow_chain = [source for source in chain if source.name in SLOW_SOURCES]
        attempts: list[SourceAttempt] = []

        if fast_chain:
            if len(fast_chain) > 1:
                pdf_url, metadata, source, fast_attempts = self._query_sources_parallel(
                    doi,
                    fast_chain,
                    phase="fast_parallel",
                    html_snapshot_callback=html_snapshot_callback,
                )
            else:
                pdf_url, metadata, source, fast_attempts = self._query_sources_sequential(
                    doi,
                    fast_chain,
                    phase="fast_sequential",
                    html_snapshot_callback=html_snapshot_callback,
                )
            attempts.extend(fast_attempts)
            if pdf_url:
                return pdf_url, metadata, source, attempts

        if slow_chain:
            logger.info(
                f"[Router] Fast sources exhausted, trying slow sources: {[s.name for s in slow_chain]}"
            )
            pdf_url, metadata, source, slow_attempts = self._query_sources_sequential(
                doi,
                slow_chain,
                phase="slow_sequential",
                html_snapshot_callback=html_snapshot_callback,
            )
            attempts.extend(slow_attempts)
            return pdf_url, metadata, source, attempts

        return None, None, None, attempts

    def _query_sources_sequential(
        self,
        doi: str,
        chain: list[PaperSource],
        *,
        phase: str,
        html_snapshot_callback: HtmlSnapshotCallback | None = None,
    ) -> tuple[Optional[str], Optional[dict], Optional[str], list[SourceAttempt]]:
        """Query sources sequentially (fallback mode)."""
        attempts: list[SourceAttempt] = []

        for priority, source in enumerate(chain, start=1):
            started_at = time.time()
            attempt: SourceAttempt = {
                "source": source.name,
                "phase": phase,
                "priority": priority,
                "started_at": started_at,
                "status": "unknown",
            }
            metadata = None
            pdf_url = None

            try:
                can_handle = source.can_handle(doi)
                attempt["can_handle"] = can_handle
                if not can_handle:
                    logger.debug(f"[Router] Skipping {source.name} (cannot handle identifier)")
                    attempt["status"] = "skipped"
                    attempt["reason"] = "cannot_handle"
                else:
                    logger.info(f"[Router] Trying {source.name} for {doi}...")
                    with self._source_trace_context(
                        source=source,
                        doi=doi,
                        phase=phase,
                        html_snapshot_callback=html_snapshot_callback,
                    ):
                        pdf_url = source.get_pdf_url(doi)
                    if pdf_url:
                        logger.info(f"[Router] SUCCESS: Found PDF via {source.name}")

                        if hasattr(source, "get_metadata"):
                            try:
                                metadata = source.get_metadata(doi)
                            except Exception as e:
                                logger.debug(f"[Router] Failed to get metadata from {source.name}: {e}")

                        if isinstance(metadata, dict):
                            metadata.setdefault("source", source.name)
                        attempt["status"] = "success"
                        attempt["pdf_url"] = pdf_url
                        attempt["metadata_found"] = bool(metadata)
                    else:
                        logger.info(f"[Router] {source.name} did not find PDF, trying next source...")
                        attempt["status"] = "no_result"
            except Exception as e:
                logger.warning(f"[Router] {source.name} error: {e}, trying next source...")
                attempt["status"] = "error"
                attempt["error"] = str(e)

            attempt["duration_ms"] = round((time.time() - started_at) * 1000.0, 3)
            attempts.append(attempt)
            if pdf_url:
                return pdf_url, metadata, source.name, attempts

        logger.warning(f"[Router] All sources failed for {doi}")
        return None, None, None, attempts

    def _query_sources_parallel(
        self,
        doi: str,
        chain: list[PaperSource],
        *,
        phase: str,
        html_snapshot_callback: HtmlSnapshotCallback | None = None,
    ) -> tuple[Optional[str], Optional[dict], Optional[str], list[SourceAttempt]]:
        """
        Query multiple sources in parallel, return first successful result.

        Strategy:
        - All sources query concurrently
        - First source to return a valid PDF URL wins
        - Respects source priority: if higher-priority source succeeds, use it
        - Cancel remaining queries once we have a good result

        Args:
            doi: The DOI to look up
            chain: Ordered list of sources (priority order)

        Returns:
            Tuple of (pdf_url, metadata, source, attempts) - all can be None
        """
        source_names = [s.name for s in chain]
        logger.info(f"[Router] Parallel query to {len(chain)} sources: {source_names}")

        workers = min(PARALLEL_QUERY_WORKERS, len(chain))

        # Track results by source name for priority handling
        results: dict[str, tuple[Optional[str], Optional[dict]]] = {}
        attempts_by_source: dict[str, SourceAttempt] = {}
        completed_sources = set()

        def query_single_source(
            source: PaperSource, priority: int
        ) -> tuple[str, Optional[str], Optional[dict], SourceAttempt]:
            """Query a single source, return (source_name, pdf_url, metadata, attempt)."""
            started_at = time.time()
            attempt: SourceAttempt = {
                "source": source.name,
                "phase": phase,
                "priority": priority,
                "started_at": started_at,
                "status": "unknown",
            }
            try:
                can_handle = source.can_handle(doi)
                attempt["can_handle"] = can_handle
                if not can_handle:
                    logger.debug(f"[Router] Skipping {source.name} (cannot handle identifier)")
                    attempt["status"] = "skipped"
                    attempt["reason"] = "cannot_handle"
                    return source.name, None, None, attempt

                logger.debug(f"[Router] Starting parallel query to {source.name}...")
                with self._source_trace_context(
                    source=source,
                    doi=doi,
                    phase=phase,
                    html_snapshot_callback=html_snapshot_callback,
                ):
                    pdf_url = source.get_pdf_url(doi)

                metadata = None
                if pdf_url and hasattr(source, "get_metadata"):
                    with contextlib.suppress(Exception):
                        metadata = source.get_metadata(doi)

                if isinstance(metadata, dict):
                    metadata.setdefault("source", source.name)
                if pdf_url:
                    attempt["status"] = "success"
                    attempt["pdf_url"] = pdf_url
                    attempt["metadata_found"] = bool(metadata)
                else:
                    attempt["status"] = "no_result"
                return source.name, pdf_url, metadata, attempt
            except Exception as e:
                logger.debug(f"[Router] {source.name} parallel query error: {e}")
                attempt["status"] = "error"
                attempt["error"] = str(e)
                return source.name, None, None, attempt
            finally:
                attempt["duration_ms"] = round((time.time() - started_at) * 1000.0, 3)

        executor = ThreadPoolExecutor(max_workers=workers)
        future_to_source = {
            executor.submit(query_single_source, source, priority): source
            for priority, source in enumerate(chain, start=1)
        }

        try:
            # Process results as they complete
            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    source_name, pdf_url, metadata, attempt = future.result()
                    attempts_by_source[source_name] = attempt
                    completed_sources.add(source_name)

                    if pdf_url:
                        results[source_name] = (pdf_url, metadata)
                        logger.info(f"[Router] {source_name} found PDF (parallel)")

                        # Check if this is the highest priority source that could succeed
                        # If so, we can return immediately
                        for priority_source in chain:
                            if priority_source.name == source_name:
                                # This is our best result so far, and it's in priority order
                                # Cancel remaining futures
                                for f in future_to_source:
                                    f.cancel()
                                self._mark_cancelled_sources(
                                    chain=chain,
                                    attempts_by_source=attempts_by_source,
                                    reason=f"Cancelled after {source_name} succeeded",
                                )
                                logger.info(
                                    f"[Router] SUCCESS: Using {source_name} (parallel, priority)"
                                )
                                return (
                                    pdf_url,
                                    metadata,
                                    source_name,
                                    self._sort_attempts(chain, attempts_by_source),
                                )
                            elif priority_source.name in results:
                                # A higher priority source already has a result
                                break
                            elif priority_source.name not in completed_sources:
                                # Higher priority source not done yet, wait for it
                                break
                    else:
                        logger.debug(f"[Router] {source_name} did not find PDF (parallel)")

                except Exception as e:
                    logger.debug(f"[Router] Future exception for {source.name}: {e}")
                    attempts_by_source[source.name] = {
                        "source": source.name,
                        "phase": phase,
                        "priority": self._priority_of(chain, source.name),
                        "status": "error",
                        "error": f"future_exception: {e}",
                    }
        finally:
            # Avoid blocking on lower-priority/slow sources once we have enough information.
            executor.shutdown(wait=False, cancel_futures=True)

        # All futures done, return best result by priority
        attempts = self._sort_attempts(chain, attempts_by_source)
        for source in chain:
            if source.name in results:
                pdf_url, metadata = results[source.name]
                if pdf_url:
                    logger.info(f"[Router] SUCCESS: Using {source.name} (parallel, best available)")
                    return pdf_url, metadata, source.name, attempts

        logger.warning(f"[Router] All sources failed for {doi} (parallel)")
        return None, None, None, attempts

    @contextlib.contextmanager
    def _source_trace_context(
        self,
        *,
        source: PaperSource,
        doi: str,
        phase: str,
        html_snapshot_callback: HtmlSnapshotCallback | None,
    ):
        """
        Bind per-source trace context into the underlying downloader when available.

        This allows FileDownloader.get_page_content() to emit HTML snapshots with
        source/identifier metadata without changing source interfaces.
        """
        if html_snapshot_callback is None:
            yield
            return

        downloader = getattr(source, "downloader", None)
        push = getattr(downloader, "push_trace_context", None)
        clear = getattr(downloader, "clear_trace_context", None)
        if not callable(push) or not callable(clear):
            yield
            return

        push(
            {
                "identifier": doi,
                "source": source.name,
                "phase": phase,
            },
            html_snapshot_callback=html_snapshot_callback,
        )
        try:
            yield
        finally:
            clear()

    @staticmethod
    def _priority_of(chain: list[PaperSource], source_name: str) -> int:
        for priority, source in enumerate(chain, start=1):
            if source.name == source_name:
                return priority
        return len(chain) + 1

    def _mark_cancelled_sources(
        self,
        *,
        chain: list[PaperSource],
        attempts_by_source: dict[str, SourceAttempt],
        reason: str,
    ) -> None:
        for priority, source in enumerate(chain, start=1):
            if source.name in attempts_by_source:
                continue
            attempts_by_source[source.name] = {
                "source": source.name,
                "phase": attempts_by_source[next(iter(attempts_by_source))].get("phase")
                if attempts_by_source
                else "parallel",
                "priority": priority,
                "status": "cancelled",
                "reason": reason,
            }

    @staticmethod
    def _sort_attempts(
        chain: list[PaperSource], attempts_by_source: dict[str, SourceAttempt]
    ) -> list[SourceAttempt]:
        order = {source.name: idx for idx, source in enumerate(chain)}
        return sorted(
            attempts_by_source.values(),
            key=lambda attempt: order.get(str(attempt.get("source")), 999),
        )

    def _get_year_smart(self, doi: str) -> Optional[int]:
        """
        Get publication year using smart lookup strategy.

        Priority:
        1. Check Unpaywall cache (free, already fetched)
        2. Check YearDetector cache (from previous lookup)
        3. Fetch from Crossref via YearDetector (as fallback)

        This avoids redundant API calls when Unpaywall data is already available.
        """
        # 1. Try Unpaywall cache first (if source exists and exposes cached metadata)
        unpaywall = self.sources.get("Unpaywall")
        get_cached_metadata = getattr(unpaywall, "get_cached_metadata", None)
        if callable(get_cached_metadata):
            cached = get_cached_metadata(doi)
            if cached and cached.get("year"):
                year = cached["year"]
                logger.debug(f"[Router] Year {year} from Unpaywall cache for {doi}")
                return year

        # 2. Try YearDetector cache (avoids creating detector if not needed)
        if self._year_detector is not None and doi in self._year_detector.cache:
            year = self._year_detector.cache[doi]
            logger.debug(f"[Router] Year {year} from YearDetector cache for {doi}")
            return year

        # 3. Fallback: fetch from Crossref via YearDetector
        logger.debug(f"[Router] Fetching year from Crossref for {doi}")
        return self.year_detector.get_year(doi)
