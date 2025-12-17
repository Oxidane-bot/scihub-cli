"""
Multi-source manager with intelligent routing and parallel querying.
"""

import contextlib
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
from urllib.parse import urlparse

from ..sources.base import PaperSource
from ..utils.logging import get_logger

logger = get_logger(__name__)

# Configuration for parallel source queries
PARALLEL_QUERY_WORKERS = 4  # Max concurrent source queries
PARALLEL_QUERY_ENABLED = True  # Can be disabled for debugging


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
        - URLs: Direct PDF -> PMC (URL-specific handlers)
        - arXiv IDs: arXiv first (direct match)
        - Papers before 2021: Sci-Hub first (high coverage), then OA sources
        - Papers 2021+: OA sources first (Sci-Hub has no coverage), then Sci-Hub
        - Unknown year: Conservative strategy (OA sources first)

        Args:
            doi: The DOI or identifier to route
            year: Publication year (will be detected if not provided)

        Returns:
            Ordered list of sources to try
        """
        # If the input is a URL, prefer URL-specific handlers first.
        parsed = urlparse(doi)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            logger.info("[Router] Detected URL input, using Direct PDF -> PMC -> HTML Landing")
            return self._build_chain(["Direct PDF", "PMC", "HTML Landing"])

        # Check if it's an arXiv ID - prioritize arXiv source
        if "arXiv" in self.sources and self.sources["arXiv"].can_handle(doi):
            logger.info("[Router] Detected arXiv ID, using arXiv -> Unpaywall -> CORE -> Sci-Hub")
            return self._build_chain(["arXiv", "Unpaywall", "CORE", "Sci-Hub"])

        # Detect year if not provided and routing is enabled (Crossref only supports DOIs)
        if year is None and self.enable_year_routing and doi.startswith("10."):
            year = self._get_year_smart(doi)

        # Build source chain based on year
        if year is None:
            # Unknown year: conservative strategy (OA first)
            logger.info(
                f"[Router] Year unknown for {doi}, using conservative strategy: Unpaywall -> arXiv -> CORE -> Sci-Hub"
            )
            chain = self._build_chain(["Unpaywall", "arXiv", "CORE", "Sci-Hub"])

        elif year < self.year_threshold:
            # Old papers: Sci-Hub has excellent coverage
            logger.info(
                f"[Router] Year {year} < {self.year_threshold}, using Sci-Hub -> Unpaywall -> arXiv -> CORE"
            )
            chain = self._build_chain(["Sci-Hub", "Unpaywall", "arXiv", "CORE"])

        else:
            # New papers: Sci-Hub has zero coverage, OA first
            logger.info(
                f"[Router] Year {year} >= {self.year_threshold}, using Unpaywall -> arXiv -> CORE -> Sci-Hub"
            )
            chain = self._build_chain(["Unpaywall", "arXiv", "CORE", "Sci-Hub"])

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
        chain = self.get_source_chain(doi, year)

        for source in chain:
            if not source.can_handle(doi):
                logger.debug(f"[Router] Skipping {source.name} (cannot handle identifier)")
                continue

            try:
                logger.info(f"[Router] Trying {source.name} for {doi}...")
                pdf_url = source.get_pdf_url(doi)
                if pdf_url:
                    logger.info(f"[Router] SUCCESS: Found PDF via {source.name}")
                    return pdf_url
                else:
                    logger.info(f"[Router] {source.name} did not find PDF, trying next source...")
            except Exception as e:
                logger.warning(f"[Router] {source.name} error: {e}, trying next source...")
                continue

        logger.warning(f"[Router] All sources failed for {doi}")
        return None

    def get_pdf_url_with_metadata(
        self, doi: str, year: Optional[int] = None
    ) -> tuple[Optional[str], Optional[dict]]:
        """
        Get PDF URL and metadata in one pass (avoids duplicate API calls).

        Uses parallel querying when enabled for faster results.

        Args:
            doi: The DOI to look up
            year: Publication year (optional, will be detected)

        Returns:
            Tuple of (pdf_url, metadata) - both can be None
        """
        chain = self.get_source_chain(doi, year)

        if PARALLEL_QUERY_ENABLED and len(chain) > 1:
            return self._query_sources_parallel(doi, chain)
        else:
            return self._query_sources_sequential(doi, chain)

    def _query_sources_sequential(
        self, doi: str, chain: list[PaperSource]
    ) -> tuple[Optional[str], Optional[dict]]:
        """Query sources sequentially (fallback mode)."""
        for source in chain:
            if not source.can_handle(doi):
                logger.debug(f"[Router] Skipping {source.name} (cannot handle identifier)")
                continue

            try:
                logger.info(f"[Router] Trying {source.name} for {doi}...")
                pdf_url = source.get_pdf_url(doi)
                if pdf_url:
                    logger.info(f"[Router] SUCCESS: Found PDF via {source.name}")

                    # Get metadata from same source (will use cache if available)
                    metadata = None
                    if hasattr(source, "get_metadata"):
                        try:
                            metadata = source.get_metadata(doi)
                        except Exception as e:
                            logger.debug(f"[Router] Failed to get metadata from {source.name}: {e}")

                    return pdf_url, metadata
                else:
                    logger.info(f"[Router] {source.name} did not find PDF, trying next source...")
            except Exception as e:
                logger.warning(f"[Router] {source.name} error: {e}, trying next source...")
                continue

        logger.warning(f"[Router] All sources failed for {doi}")
        return None, None

    def _query_sources_parallel(
        self, doi: str, chain: list[PaperSource]
    ) -> tuple[Optional[str], Optional[dict]]:
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
            Tuple of (pdf_url, metadata) - both can be None
        """
        source_names = [s.name for s in chain]
        logger.info(f"[Router] Parallel query to {len(chain)} sources: {source_names}")

        workers = min(PARALLEL_QUERY_WORKERS, len(chain))

        # Track results by source name for priority handling
        results: dict[str, tuple[Optional[str], Optional[dict]]] = {}
        completed_sources = set()

        def query_single_source(source: PaperSource) -> tuple[str, Optional[str], Optional[dict]]:
            """Query a single source, return (source_name, pdf_url, metadata)."""
            try:
                if not source.can_handle(doi):
                    logger.debug(f"[Router] Skipping {source.name} (cannot handle identifier)")
                    return source.name, None, None

                logger.debug(f"[Router] Starting parallel query to {source.name}...")
                pdf_url = source.get_pdf_url(doi)

                metadata = None
                if pdf_url and hasattr(source, "get_metadata"):
                    with contextlib.suppress(Exception):
                        metadata = source.get_metadata(doi)

                return source.name, pdf_url, metadata
            except Exception as e:
                logger.debug(f"[Router] {source.name} parallel query error: {e}")
                return source.name, None, None

        executor = ThreadPoolExecutor(max_workers=workers)
        future_to_source = {
            executor.submit(query_single_source, source): source for source in chain
        }

        try:
            # Process results as they complete
            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    source_name, pdf_url, metadata = future.result()
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
                                logger.info(
                                    f"[Router] SUCCESS: Using {source_name} (parallel, priority)"
                                )
                                return pdf_url, metadata
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
        finally:
            # Avoid blocking on lower-priority/slow sources once we have enough information.
            executor.shutdown(wait=False, cancel_futures=True)

        # All futures done, return best result by priority
        for source in chain:
            if source.name in results:
                pdf_url, metadata = results[source.name]
                if pdf_url:
                    logger.info(f"[Router] SUCCESS: Using {source.name} (parallel, best available)")
                    return pdf_url, metadata

        logger.warning(f"[Router] All sources failed for {doi} (parallel)")
        return None, None

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
