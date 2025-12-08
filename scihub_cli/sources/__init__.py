"""
Multi-source paper download system.
"""

from .arxiv_source import ArxivSource
from .base import PaperSource
from .core_source import CORESource
from .scihub_source import SciHubSource
from .unpaywall_source import UnpaywallSource

__all__ = ["PaperSource", "SciHubSource", "UnpaywallSource", "CORESource", "ArxivSource"]
