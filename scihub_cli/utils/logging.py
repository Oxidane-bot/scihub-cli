"""
Logging configuration for Sci-Hub CLI.
"""

import logging
import sys


def setup_logging(verbose: bool = False, log_file: str = None) -> logging.Logger:
    """Set up logging configuration."""
    # Import here to avoid circular imports
    from ..config.settings import settings

    # Attempt to reconfigure console for UTF-8 output on Windows
    if sys.platform == "win32":
        try:
            if sys.stdout.isatty() and sys.stdout.encoding.lower() != "utf-8":
                sys.stdout.reconfigure(encoding="utf-8")
            if sys.stderr.isatty() and sys.stderr.encoding.lower() != "utf-8":
                sys.stderr.reconfigure(encoding="utf-8")
        except Exception as e:
            print(f"Warning: Could not reconfigure console to UTF-8: {e}", file=sys.stderr)

    # Set logging level
    level = logging.DEBUG if verbose else logging.INFO

    # Use provided log file or default
    log_file_path = log_file or settings.log_file

    # Configure logging
    logging.basicConfig(
        level=level,
        format=settings.LOG_FORMAT,
        handlers=[
            logging.FileHandler(log_file_path, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    return logging.getLogger(__name__)


def get_logger(name: str = __name__) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)
