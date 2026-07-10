"""Install the bundled SciHub CLI skill into supported coding agents."""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from importlib.resources import files
from pathlib import Path

SKILL_NAME = "scihub-cli"
DEFAULT_TARGETS = ("codex", "claude-code", "gemini-cli", "copilot", "openclaw", "opencode")
SUPPORTED_TARGETS = DEFAULT_TARGETS


def _home() -> Path:
    return Path.home()


def target_paths() -> dict[str, Path]:
    """Return the user-level Skill directory for each supported agent."""
    codex_home = Path(os.environ.get("CODEX_HOME", _home() / ".codex"))
    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", _home() / ".claude"))
    gemini_home = Path(os.environ.get("GEMINI_HOME", _home() / ".gemini"))
    return {
        "codex": codex_home / "skills" / SKILL_NAME,
        "claude-code": claude_home / "skills" / SKILL_NAME,
        "copilot": _home() / ".copilot" / "skills" / SKILL_NAME,
        "openclaw": _home() / ".openclaw" / "skills" / SKILL_NAME,
        "opencode": _home() / ".config" / "opencode" / "skills" / SKILL_NAME,
        "gemini-cli": gemini_home / "skills" / SKILL_NAME,
    }


def _skill_source() -> Path:
    return Path(str(files("scihub_cli").joinpath("scihub-cli.SKILL.md")))


def install_skill(targets: list[str], *, force: bool = False) -> list[Path]:
    """Copy the bundled Skill into the selected agents and return installed paths."""
    source = _skill_source()
    destinations = target_paths()
    installed: list[Path] = []

    for target in targets:
        destination = destinations[target]
        if destination.exists() and not force:
            raise FileExistsError(
                f"{destination} already exists; use --force to replace the installed Skill"
            )
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination / "SKILL.md")
        installed.append(destination)
    return installed


def _parse_targets(values: list[str] | None) -> list[str]:
    requested = values or ["all"]
    selected: list[str] = []
    for value in requested:
        for target in value.split(","):
            target = target.strip().lower()
            if target == "all":
                selected.extend(DEFAULT_TARGETS)
            elif target in SUPPORTED_TARGETS:
                selected.append(target)
            else:
                raise ValueError(
                    f"Unsupported target {target!r}. Choose: all, {', '.join(SUPPORTED_TARGETS)}"
                )
    return list(dict.fromkeys(selected))


def main(argv: list[str] | None = None) -> int:
    """Run the ``scihub-cli skill`` command group."""
    parser = argparse.ArgumentParser(
        prog="scihub-cli skill",
        description="Install the bundled SciHub CLI Skill into coding agents.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    install = subparsers.add_parser("install", help="Install the Skill into one or more agents")
    install.add_argument(
        "--target",
        action="append",
        metavar="TARGET",
        help=(
            "all (default), codex, claude-code, gemini-cli, copilot, openclaw, or opencode; "
            "repeat or use commas"
        ),
    )
    install.add_argument("--force", action="store_true", help="Replace an existing Skill")

    args = parser.parse_args(argv)
    if args.command != "install":
        return 2
    try:
        installed = install_skill(_parse_targets(args.target), force=args.force)
    except (FileExistsError, ValueError) as error:
        parser.error(str(error))

    for path in installed:
        print(f"Installed {SKILL_NAME} Skill: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
