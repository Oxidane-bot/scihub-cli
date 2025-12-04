"""
Application settings and configuration for Sci-Hub CLI.
"""

import os
from pathlib import Path
from typing import Any


class Settings:
    """Centralized application settings."""

    # Default settings
    DEFAULT_OUTPUT_DIR = "./downloads"
    DEFAULT_TIMEOUT = 30
    DEFAULT_RETRIES = 3
    DEFAULT_PARALLEL = 3
    # No default email - user must configure

    # File and content validation
    MIN_FILE_SIZE = 10000  # Less than 10KB is suspicious
    CHUNK_SIZE = 8192

    # Filename settings
    MAX_FILENAME_LENGTH = 100
    MAX_TITLE_LENGTH = 80

    # Multi-source settings
    YEAR_THRESHOLD = 2021  # Papers before this year: Sci-Hub first; after: OA first
    ENABLE_YEAR_ROUTING = True  # Enable intelligent year-based source routing

    # Logging settings
    LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"

    def __init__(self):
        """Initialize settings with config file and environment variable support."""
        self.output_dir = os.getenv("SCIHUB_OUTPUT_DIR", self.DEFAULT_OUTPUT_DIR)
        self.timeout = int(os.getenv("SCIHUB_TIMEOUT", self.DEFAULT_TIMEOUT))
        self.retries = int(os.getenv("SCIHUB_RETRIES", self.DEFAULT_RETRIES))
        self.parallel = int(os.getenv("SCIHUB_PARALLEL", self.DEFAULT_PARALLEL))
        self.year_threshold = int(os.getenv("SCIHUB_YEAR_THRESHOLD", self.YEAR_THRESHOLD))
        self.enable_year_routing = (
            os.getenv("SCIHUB_ENABLE_ROUTING", str(self.ENABLE_YEAR_ROUTING)).lower() == "true"
        )

        # Email configuration priority:
        # 1. Environment variable (for backward compatibility)
        # 2. Config file
        # 3. None (will prompt user)
        from .user_config import user_config

        self.email = os.getenv("SCIHUB_CLI_EMAIL") or user_config.get_email()

        # CORE API key (optional, improves rate limits)
        self.core_api_key = os.getenv("CORE_API_KEY") or user_config.get_core_api_key()

        # Logging configuration
        user_home = str(Path.home())
        self.log_dir = os.path.join(user_home, ".scihub-cli", "logs")
        os.makedirs(self.log_dir, exist_ok=True)
        self.log_file = os.path.join(self.log_dir, "scihub-dl.log")

    def get_dict(self) -> dict[str, Any]:
        """Return settings as dictionary."""
        return {
            "output_dir": self.output_dir,
            "timeout": self.timeout,
            "retries": self.retries,
            "parallel": self.parallel,
            "email": self.email,
            "year_threshold": self.year_threshold,
            "enable_year_routing": self.enable_year_routing,
            "log_dir": self.log_dir,
            "log_file": self.log_file,
        }

    def update(self, **kwargs):
        """Update settings with provided values."""
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)


# Global settings instance
settings = Settings()
