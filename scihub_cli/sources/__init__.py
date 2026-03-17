"""
Multi-source paper download system.
"""

from .arxiv_source import ArxivSource
from .base import PaperSource
from .base_oai_source import BASESource
from .core_source import CORESource
from .direct_pdf_source import DirectPDFSource
from .europe_pmc_oa_source import EuropePMCOASource
from .html_landing_source import HTMLLandingSource
from .openaire_source import OpenAireSource
from .openalex_source import OpenAlexSource
from .osti_source import OSTISource
from .pmc_source import PMCSource
from .scihub_source import SciHubSource
from .semantic_scholar_source import SemanticScholarSource
from .unpaywall_source import UnpaywallSource

__all__ = [
    "PaperSource",
    "SciHubSource",
    "UnpaywallSource",
    "CORESource",
    "ArxivSource",
    "OpenAlexSource",
    "SemanticScholarSource",
    "OpenAireSource",
    "EuropePMCOASource",
    "DirectPDFSource",
    "OSTISource",
    "PMCSource",
    "HTMLLandingSource",
    "BASESource",
]
