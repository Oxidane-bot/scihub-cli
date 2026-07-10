from pathlib import Path

import pytest

from scihub_cli import skill_installer


def test_parse_targets_defaults_to_all():
    assert skill_installer._parse_targets(None) == list(skill_installer.DEFAULT_TARGETS)


def test_parse_targets_accepts_repeated_and_comma_separated_values():
    assert skill_installer._parse_targets(["codex,gemini-cli", "claude-code", "codex"]) == [
        "codex",
        "gemini-cli",
        "claude-code",
    ]


def test_parse_targets_rejects_unknown_target():
    with pytest.raises(ValueError, match="Unsupported target"):
        skill_installer._parse_targets(["cursor"])


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
