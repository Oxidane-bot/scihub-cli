"""
User configuration file management.

Handles ~/.scihub-cli/config.json for persistent user settings.
"""

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ..utils.logging import get_logger

logger = get_logger(__name__)


class UserConfig:
    """Manages user configuration file in ~/.scihub-cli/config.json"""

    _CONFIG_DIR_MODE = 0o700
    _CONFIG_FILE_MODE = 0o600

    def __init__(self):
        # Use user's home directory (cross-platform)
        self.config_dir = Path.home() / ".scihub-cli"
        self.config_file = self.config_dir / "config.json"
        self._config: dict[str, Any] | None = None

    def _ensure_config_dir(self):
        """Create config directory if it doesn't exist."""
        if not self.config_dir.exists():
            self.config_dir.mkdir(
                parents=True,
                exist_ok=True,
                mode=self._CONFIG_DIR_MODE,
            )
            logger.info(f"Created config directory: {self.config_dir}")
        self._harden_permissions(self.config_dir, self._CONFIG_DIR_MODE)

    @staticmethod
    def _harden_permissions(path: Path, mode: int) -> None:
        """Restrict a user-owned config path when the platform supports modes."""
        if os.name == "nt":
            return
        try:
            path.chmod(mode)
        except OSError as e:
            # Configuration remains usable on filesystems that do not expose
            # POSIX modes, but make the issue visible to the user.
            logger.warning("Could not restrict permissions for %s: %s", path, e)

    def load(self) -> dict[str, Any]:
        """Load configuration from file."""
        if self._config is not None:
            return self._config

        if not self.config_file.exists():
            logger.debug(f"Config file not found: {self.config_file}")
            self._config = {}
            return self._config

        try:
            # Repair permissions on files created by older releases before
            # reading credentials/API keys from them.
            self._ensure_config_dir()
            self._harden_permissions(self.config_file, self._CONFIG_FILE_MODE)
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

        temporary_path: Path | None = None
        try:
            # Write atomically through a mode-600 temporary file.  This avoids
            # exposing a newly-created config with the process umask's default
            # permissions and prevents readers from seeing partial JSON.
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.config_dir,
                prefix=".config.",
                suffix=".tmp",
                delete=False,
            ) as f:
                temporary_path = Path(f.name)
                self._harden_permissions(temporary_path, self._CONFIG_FILE_MODE)
                json.dump(config, f, indent=2, ensure_ascii=False)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(temporary_path, self.config_file)
            self._harden_permissions(self.config_file, self._CONFIG_FILE_MODE)
            self._config = config
            logger.info(f"Saved config to {self.config_file}")
        except Exception as e:
            if temporary_path is not None:
                with contextlib.suppress(OSError):
                    temporary_path.unlink(missing_ok=True)
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

    def get_email(self) -> str | None:
        """Get email from config file."""
        return self.get("email")

    def set_email(self, email: str):
        """Set email in config file."""
        self.set("email", email)

    def get_core_api_key(self) -> str | None:
        """Get CORE API key from config file."""
        return self.get("core_api_key")

    def set_core_api_key(self, api_key: str):
        """Set CORE API key in config file."""
        self.set("core_api_key", api_key)

    def get_openalex_api_key(self) -> str | None:
        """Get OpenAlex API key from config file."""
        return self.get("openalex_api_key")

    def set_openalex_api_key(self, api_key: str):
        """Set OpenAlex API key in config file."""
        self.set("openalex_api_key", api_key)

    def exists(self) -> bool:
        """Check if config file exists."""
        return self.config_file.exists()

    def get_config_path(self) -> str:
        """Get the config file path as string."""
        return str(self.config_file)


# Global user config instance
user_config = UserConfig()
