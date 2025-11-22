# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sci-Hub CLI is a Python command-line tool for batch downloading academic papers from Sci-Hub mirrors. The tool features a modular architecture with intelligent mirror selection, automatic fallback mechanisms, and metadata-based PDF naming.

## Architecture

### Modular Structure (High Cohesion, Low Coupling)

```
scihub_cli/
├── client.py                    # Main orchestrator (SciHubClient)
├── scihub_dl_refactored.py     # Entry point and CLI interface
├── metadata_utils.py           # Paper metadata extraction
├── stealth_utils.py            # Legacy stealth utilities (unused)
├── core/                       # Core business logic
│   ├── downloader.py          # File download operations
│   ├── doi_processor.py       # DOI normalization and formatting
│   ├── file_manager.py        # Filename generation and validation
│   ├── mirror_manager.py      # Mirror testing and selection
│   └── parser.py              # HTML parsing and URL extraction
├── network/                    # Network layer
│   ├── bypass.py              # Cloudflare detection (unused)
│   ├── proxy.py               # Proxy rotation (unused)
│   └── session.py             # HTTP session management
├── config/                     # Configuration
│   ├── mirrors.py             # Mirror definitions
│   └── settings.py            # Application settings
└── utils/                      # Utilities
    ├── logging.py             # Logging setup
    └── retry.py               # Retry mechanism with backoff
```

### Core Components

- **`client.py`**: High-level orchestrator using dependency injection
- **`scihub_dl_refactored.py`**: CLI entry point (used by `scihub-cli` command)
- **`core/`**: Single-responsibility modules for core functionality
- **`network/`**: Network operations and session management
- **`config/`**: Centralized configuration
- **`utils/`**: Reusable utilities

### Key Features

- **Modular Architecture**: Clean separation of concerns with dependency injection
- **Intelligent Fallback**: Automatically tries formatted DOI → original DOI when extraction fails
- **Tiered Mirror Selection**: Tests easy mirrors first, then hard mirrors (sci-hub.se)
- **Metadata-based Filenames**: Creates descriptive filenames like `[2013] - Nanometre-scale thermometry in a living cell.pdf`
- **Robust Error Handling**: Automatic retries with exponential backoff
- **Code Quality**: Passes ruff linting with no issues

## Development Commands

### Installation and Setup
```bash
# Install with uv (recommended)
uv tool install .

# Install dependencies for development
uv pip install -r requirements.txt
```

### Running the Application
```bash
# Basic usage
scihub-cli papers.txt

# With verbose logging and custom output
scihub-cli papers.txt -o downloads -v

# Target specific mirror
scihub-cli papers.txt -m https://sci-hub.se -v

# Specify retries and timeout
scihub-cli papers.txt -r 5 -t 60
```

### Testing
```bash
# Run all tests
uv run python -m unittest discover tests/

# Quick test with a single DOI
echo "10.1038/nature12373" > test.txt
scihub-cli test.txt -v
```

### Code Quality
```bash
# Run linter
uv run ruff check scihub_cli/ tests/

# Auto-fix issues
uv run ruff check --fix scihub_cli/ tests/
```

## Implementation Details

### Fallback Strategy

The system implements a robust two-tier fallback mechanism:

1. **Formatted DOI URL**: `https://sci-hub.ee/10.1038@nature12373` (@ replaces /)
2. **Original DOI URL**: `https://sci-hub.ee/10.1038/nature12373` (if first fails)

This is implemented in `client.py:_download_single_paper()` and handles cases where:
- HTTP request succeeds but HTML parsing fails
- Some mirrors work better with original DOI format

### Mirror Management

The `MirrorManager` tests mirrors in tiers:

**Tier 1 (Easy)**: No Cloudflare protection
- https://www.sci-hub.ee
- https://sci-hub.ru
- https://sci-hub.ren
- https://sci-hub.wf

**Tier 2 (Hard)**: Strong Cloudflare protection
- https://sci-hub.se (last resort)

### Dependency Injection

The `SciHubClient` uses constructor injection for testability:

```python
client = SciHubClient(
    output_dir='downloads',
    mirrors=['https://sci-hub.ee'],
    timeout=30,
    retries=3,
    mirror_manager=custom_manager,  # Optional injection
    parser=custom_parser,            # Optional injection
    # ... more injectable dependencies
)
```

### Error Handling

- **Retry Logic**: Exponential backoff (2s, 4s, 8s, ...)
- **File Validation**: Checks file size (< 10KB = suspicious)
- **Fallback Mechanism**: Automatic format switching on parse failure
- **Graceful Degradation**: Returns None on failure, never crashes

## Configuration

Key settings in `config/settings.py`:
- Default output: `./downloads`
- Timeout: 30 seconds
- Retries: 3 attempts
- Parallel downloads: 3 (sequential for now)
- Chunk size: 8192 bytes

## Success Metrics

The modular refactored implementation:
- ✅ Modular architecture with high cohesion, low coupling
- ✅ Dependency injection for better testability
- ✅ Robust fallback mechanism (formatted → original DOI)
- ✅ Tiered mirror selection (easy → hard)
- ✅ Preserved metadata extraction and filename generation
- ✅ Clean code passing all ruff checks
- ✅ Successfully downloads papers with intelligent retries
