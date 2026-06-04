# Installation

## Install from PyPI (recommended)

```bash
pip install scihub-cli
```

## Global Install (uv)

```bash
uv tool install scihub-cli
```

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
