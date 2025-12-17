"""
Multi-source paper download system.
"""

from .arxiv_source import ArxivSource
from .base import PaperSource
from .core_source import CORESource
from .direct_pdf_source import DirectPDFSource
from .html_landing_source import HTMLLandingSource
from .pmc_source import PMCSource
from .scihub_source import SciHubSource
from .unpaywall_source import UnpaywallSource

__all__ = [
    "PaperSource",
    "SciHubSource",
    "UnpaywallSource",
    "CORESource",
    "ArxivSource",
    "DirectPDFSource",
    "PMCSource",
    "HTMLLandingSource",
]
