"""
Multi-source manager with intelligent routing.
"""

from typing import Optional

from ..sources.base import PaperSource
from ..utils.logging import get_logger
from .year_detector import YearDetector

logger = get_logger(__name__)


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
        self.year_detector = YearDetector() if enable_year_routing else None

    def get_source_chain(self, doi: str, year: Optional[int] = None) -> list[PaperSource]:
        """
        Get the optimal source chain for a given DOI based on publication year.

        Strategy:
        - Papers before 2021: Sci-Hub first (high coverage), then OA sources
        - Papers 2021+: OA sources first (Sci-Hub has no coverage), then Sci-Hub
        - Unknown year: Conservative strategy (OA sources first)

        Args:
            doi: The DOI to route
            year: Publication year (will be detected if not provided)

        Returns:
            Ordered list of sources to try
        """
        # Detect year if not provided and routing is enabled
        if year is None and self.enable_year_routing and self.year_detector:
            year = self.year_detector.get_year(doi)

        # Build source chain based on year
        if year is None:
            # Unknown year: conservative strategy (OA first)
            logger.info(
                f"[Router] Year unknown for {doi}, using conservative strategy: Unpaywall -> CORE -> Sci-Hub"
            )
            chain = self._build_chain(["Unpaywall", "CORE", "Sci-Hub"])

        elif year < self.year_threshold:
            # Old papers: Sci-Hub has excellent coverage
            logger.info(
                f"[Router] Year {year} < {self.year_threshold}, using Sci-Hub -> Unpaywall -> CORE"
            )
            chain = self._build_chain(["Sci-Hub", "Unpaywall", "CORE"])

        else:
            # New papers: Sci-Hub has zero coverage, OA first
            logger.info(
                f"[Router] Year {year} >= {self.year_threshold}, using Unpaywall -> CORE -> Sci-Hub"
            )
            chain = self._build_chain(["Unpaywall", "CORE", "Sci-Hub"])

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

        Args:
            doi: The DOI to look up
            year: Publication year (optional, will be detected)

        Returns:
            Tuple of (pdf_url, metadata) - both can be None
        """
        chain = self.get_source_chain(doi, year)

        for source in chain:
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
