"""
Sci-Hub CLI package.

A command-line tool for batch downloading academic papers from Sci-Hub.
"""

__version__ = "0.4.1"

# Import main interfaces for easy access
from .client import SciHubClient
from .models import DownloadProgress, DownloadResult

# Export commonly used classes and functions
__all__ = [
    "SciHubClient",
    "DownloadProgress",
    "DownloadResult",
]
