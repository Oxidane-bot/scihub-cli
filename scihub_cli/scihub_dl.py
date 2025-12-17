"""
Backward-compatible module entrypoint.

Historically, documentation referenced `python -m scihub_cli.scihub_dl ...`.
This module keeps that working while delegating to the refactored CLI.
"""

import sys

from .scihub_dl_refactored import SciHubDownloader, main

__all__ = ["SciHubDownloader", "main"]


if __name__ == "__main__":
    sys.exit(main())
