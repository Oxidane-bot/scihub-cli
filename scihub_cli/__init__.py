"""
Sci-Hub CLI package.

A command-line tool for batch downloading academic papers from Sci-Hub.
"""

__version__ = "0.2.0"

# Import main interfaces for easy access
from .client import SciHubClient
from .scihub_dl_refactored import SciHubDownloader, main

# Export commonly used classes and functions
__all__ = [
    'SciHubClient',
    'SciHubDownloader',  # Legacy compatibility
    'main'
] 