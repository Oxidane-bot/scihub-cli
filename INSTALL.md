# Installation

## Install from PyPI (recommended)

```bash
pip install scihub-cli
```

## Global Install (uv)

```bash
uv tool install scihub-cli
```

## Install the bundled AI coding-agent Skill

After installing the CLI, install its bundled Skill into all supported user-level agents:

```bash
scihub-cli skill install
```

Supported targets are Codex, Claude Code, and Gemini CLI. To install only selected targets, use
`--target`; repeat it or supply a comma-separated list. Existing Skills are protected unless
`--force` is specified.

```bash
scihub-cli skill install --target codex,claude-code
scihub-cli skill install --target gemini-cli --force
```

This installs a local Skill that tells the agent how to prepare inputs, invoke `scihub-cli`, and
verify download results. It does not configure an MCP server.

## Temporary Run

```bash
uvx scihub-cli papers.txt
```

## Run From Source (uv)

```bash
git clone https://github.com/Oxidane-bot/scihub-cli.git
cd scihub-cli
uv sync --frozen
uv run python -m scihub_cli papers.txt
```

## Development Setup

```bash
uv sync --dev
```
