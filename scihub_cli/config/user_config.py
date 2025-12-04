"""
User configuration file management.

Handles ~/.scihub-cli/config.json for persistent user settings.
"""

import json
from pathlib import Path
from typing import Any, Optional

from ..utils.logging import get_logger

logger = get_logger(__name__)


class UserConfig:
    """Manages user configuration file in ~/.scihub-cli/config.json"""

    def __init__(self):
        # Use user's home directory (cross-platform)
        self.config_dir = Path.home() / ".scihub-cli"
        self.config_file = self.config_dir / "config.json"
        self._config: Optional[dict[str, Any]] = None

    def _ensure_config_dir(self):
        """Create config directory if it doesn't exist."""
        if not self.config_dir.exists():
            self.config_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Created config directory: {self.config_dir}")

    def load(self) -> dict[str, Any]:
        """Load configuration from file."""
        if self._config is not None:
            return self._config

        if not self.config_file.exists():
            logger.debug(f"Config file not found: {self.config_file}")
            self._config = {}
            return self._config

        try:
            with open(self.config_file, encoding="utf-8") as f:
                self._config = json.load(f)
            logger.debug(f"Loaded config from {self.config_file}")
            return self._config
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON in config file: {e}. Using empty config.")
            self._config = {}
            return self._config
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            self._config = {}
            return self._config

    def save(self, config: dict[str, Any]):
        """Save configuration to file."""
        self._ensure_config_dir()

        try:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            self._config = config
            logger.info(f"Saved config to {self.config_file}")
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            raise

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        config = self.load()
        return config.get(key, default)

    def set(self, key: str, value: Any):
        """Set a configuration value and save."""
        config = self.load()
        config[key] = value
        self.save(config)

    def get_email(self) -> Optional[str]:
        """Get email from config file."""
        return self.get("email")

    def set_email(self, email: str):
        """Set email in config file."""
        self.set("email", email)

    def get_core_api_key(self) -> Optional[str]:
        """Get CORE API key from config file."""
        return self.get("core_api_key")

    def set_core_api_key(self, api_key: str):
        """Set CORE API key in config file."""
        self.set("core_api_key", api_key)

    def exists(self) -> bool:
        """Check if config file exists."""
        return self.config_file.exists()

    def get_config_path(self) -> str:
        """Get the config file path as string."""
        return str(self.config_file)


# Global user config instance
user_config = UserConfig()
