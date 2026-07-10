from pathlib import Path

import pytest

from scihub_cli import skill_installer


def test_parse_targets_defaults_to_all():
    assert skill_installer._parse_targets(None) == list(skill_installer.DEFAULT_TARGETS)


def test_parse_targets_accepts_repeated_and_comma_separated_values():
    assert skill_installer._parse_targets(["codex,openclaw", "opencode", "codex"]) == [
        "codex",
        "openclaw",
        "opencode",
    ]


def test_parse_targets_accepts_gemini_cli_explicitly():
    assert skill_installer._parse_targets(["gemini-cli"]) == ["gemini-cli"]


def test_parse_targets_rejects_cursor_without_a_native_skill_path():
    with pytest.raises(ValueError, match="Unsupported target"):
        skill_installer._parse_targets(["cursor"])


def test_target_paths_use_documented_personal_skill_locations(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(skill_installer, "_home", lambda: tmp_path)

    paths = skill_installer.target_paths()

    assert paths["copilot"] == tmp_path / ".copilot" / "skills" / "scihub-cli"
    assert paths["openclaw"] == tmp_path / ".openclaw" / "skills" / "scihub-cli"
    assert paths["opencode"] == tmp_path / ".config" / "opencode" / "skills" / "scihub-cli"


def test_install_skill_copies_the_bundled_skill(monkeypatch, tmp_path: Path):
    paths = {target: tmp_path / target / "skills" / "scihub-cli" for target in skill_installer.DEFAULT_TARGETS}
    monkeypatch.setattr(skill_installer, "target_paths", lambda: paths)

    installed = skill_installer.install_skill(["codex"])

    assert installed == [paths["codex"]]
    content = (paths["codex"] / "SKILL.md").read_text(encoding="utf-8")
    assert content.startswith("---\nname: scihub-cli\n")


def test_install_skill_requires_force_to_replace(monkeypatch, tmp_path: Path):
    paths = {target: tmp_path / target / "skills" / "scihub-cli" for target in skill_installer.DEFAULT_TARGETS}
    monkeypatch.setattr(skill_installer, "target_paths", lambda: paths)
    skill_installer.install_skill(["codex"])

    with pytest.raises(FileExistsError):
        skill_installer.install_skill(["codex"])

    skill_installer.install_skill(["codex"], force=True)
