import os
from pathlib import Path

import pytest

from scihub_cli.config.user_config import UserConfig


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not portable on Windows")
def test_user_config_save_restricts_directory_and_file_permissions(tmp_path: Path):
    config = UserConfig()
    config.config_dir = tmp_path / ".scihub-cli"
    config.config_file = config.config_dir / "config.json"

    config.save({"email": "user@example.org", "core_api_key": "secret"})

    assert config.config_dir.stat().st_mode & 0o777 == 0o700
    assert config.config_file.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits are not portable on Windows")
def test_user_config_load_repairs_existing_permissions(tmp_path: Path):
    config_dir = tmp_path / ".scihub-cli"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text('{"email": "user@example.org"}', encoding="utf-8")
    config_dir.chmod(0o755)
    config_file.chmod(0o644)

    config = UserConfig()
    config.config_dir = config_dir
    config.config_file = config_file

    assert config.load()["email"] == "user@example.org"
    assert config_dir.stat().st_mode & 0o777 == 0o700
    assert config_file.stat().st_mode & 0o777 == 0o600
