#!/usr/bin/env python3
"""
Sci-Hub Batch Downloader - Refactored Version

A command-line tool to batch download academic papers from Sci-Hub.
This is the backward-compatible interface that uses the new modular architecture.
"""

import argparse
import sys

from .client import SciHubClient
from .config.settings import settings
from .config.user_config import user_config
from .utils.logging import get_logger, setup_logging


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Multi-source academic paper downloader.",
        epilog="v0.2.0 - Sources: Sci-Hub, Unpaywall, CORE | Features: intelligent routing",
    )

    parser.add_argument("input_file", help="Text file containing DOIs or URLs (one per line)")
    parser.add_argument(
        "-o",
        "--output",
        default=settings.output_dir,
        help=f"Output directory for downloaded PDFs (default: {settings.output_dir})",
    )
    parser.add_argument("-m", "--mirror", help="Specific Sci-Hub mirror to use")
    parser.add_argument(
        "-t",
        "--timeout",
        type=int,
        default=settings.timeout,
        help=f"Request timeout in seconds (default: {settings.timeout})",
    )
    parser.add_argument(
        "-r",
        "--retries",
        type=int,
        default=settings.retries,
        help=f"Number of retries for failed downloads (default: {settings.retries})",
    )
    parser.add_argument(
        "-p",
        "--parallel",
        type=int,
        default=settings.parallel,
        help="Reserved; downloads are processed sequentially",
    )
    parser.add_argument("--email", help="Email for Unpaywall API (saves to config file)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")
    parser.add_argument("--version", action="version", version="scihub-cli v0.2.0")

    args = parser.parse_args()

    # Set up logging
    setup_logging(verbose=args.verbose)
    logger = get_logger(__name__)

    # Handle email configuration
    email = args.email or settings.email
    if args.email:
        user_config.set_email(args.email)
        logger.info(f"Email saved to config: {args.email}")
    elif not email:
        logger.info("No email configured; Unpaywall will be disabled for this run")

    # Initialize client with parameters
    mirrors = [args.mirror] if args.mirror else None
    client = SciHubClient(
        output_dir=args.output,
        mirrors=mirrors,
        timeout=args.timeout,
        retries=args.retries,
        email=email,
    )

    # Download papers
    try:
        results = client.download_from_file(args.input_file, args.parallel)

        # Print failures if any
        failures = [(identifier, result) for identifier, result in results if not result]
        if failures:
            logger.warning("The following papers failed to download:")
            for identifier, _ in failures:
                logger.warning(f"  - {identifier}")

        return 0 if len(failures) == 0 else 1

    except Exception as e:
        logger.error(f"An error occurred: {e}")
        return 1


# Backward compatibility: expose the old SciHubDownloader class interface
class SciHubDownloader:
    """Legacy interface for backward compatibility."""

    def __init__(self, output_dir=None, mirror=None, timeout=None, retries=None):
        """Initialize with legacy interface."""
        mirrors = [mirror] if mirror else None
        self.client = SciHubClient(
            output_dir=output_dir, mirrors=mirrors, timeout=timeout, retries=retries
        )

    def download_paper(self, identifier):
        """Download a paper (legacy interface)."""
        return self.client.download_paper(identifier)

    def download_from_file(self, input_file, parallel=None):
        """Download from file (legacy interface)."""
        return self.client.download_from_file(input_file, parallel)


if __name__ == "__main__":
    sys.exit(main())
