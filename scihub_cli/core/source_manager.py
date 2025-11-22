"""
Multi-source manager with intelligent routing.
"""

from typing import List, Optional
from ..sources.base import PaperSource
from .year_detector import YearDetector
from ..utils.logging import get_logger

logger = get_logger(__name__)


class SourceManager:
    """Manages multiple paper sources with intelligent routing based on publication year."""

    def __init__(self,
                 sources: List[PaperSource],
                 year_threshold: int = 2021,
                 enable_year_routing: bool = True):
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

    def get_source_chain(self, doi: str, year: Optional[int] = None) -> List[PaperSource]:
        """
        Get the optimal source chain for a given DOI based on publication year.

        Strategy:
        - Papers before 2021: Sci-Hub first (high coverage), then Unpaywall
        - Papers 2021+: Unpaywall first (Sci-Hub has no coverage), then Sci-Hub
        - Unknown year: Conservative strategy (Unpaywall first)

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
            logger.info(f"[Router] Year unknown for {doi}, using conservative strategy: Unpaywall -> Sci-Hub")
            chain = self._build_chain(["Unpaywall", "Sci-Hub"])

        elif year < self.year_threshold:
            # Old papers: Sci-Hub has excellent coverage
            logger.info(f"[Router] Year {year} < {self.year_threshold}, using Sci-Hub -> Unpaywall")
            chain = self._build_chain(["Sci-Hub", "Unpaywall"])

        else:
            # New papers: Sci-Hub has zero coverage, OA first
            logger.info(f"[Router] Year {year} >= {self.year_threshold}, using Unpaywall -> Sci-Hub")
            chain = self._build_chain(["Unpaywall", "Sci-Hub"])

        return chain

    def _build_chain(self, source_names: List[str]) -> List[PaperSource]:
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
