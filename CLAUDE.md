# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sci-Hub CLI is a Python command-line tool optimized for bypassing Cloudflare protection on sci-hub.se and other Sci-Hub mirrors. The tool extracts DOIs/URLs from input files, intelligently bypasses anti-bot measures, and downloads PDFs with metadata-based naming.

## Architecture

### Core Components

- **`scihub_cli/scihub_dl.py`**: Main downloader with `CloudflareBypassManager` and `SciHubDownloader` classes
- **`scihub_cli/metadata_utils.py`**: Metadata extraction utilities for generating descriptive filenames
- **`scihub_cli/stealth_utils.py`**: Stealth utilities including proxy rotation and browser fingerprinting

### Key Features

- **Advanced Cloudflare Bypass**: Uses cloudscraper library optimized for sci-hub.se
- **Multi-Strategy Fallback**: Automatically tries cloudscraper → requests-html → basic requests
- **Intelligent Mirror Selection**: Tests mirrors and selects working ones with bypass capabilities
- **Metadata-based Filenames**: Creates descriptive filenames like `[2020] - Array programming with NumPy.pdf`
- **Robust Error Handling**: Automatic retries with exponential backoff

## Development Commands

### Installation and Setup
```bash
# Install with uv (recommended)
uv tool install .

# Install dependencies for development
pip install -r requirements.txt
```

### Running the Application
```bash
# Basic usage
scihub-cli papers.txt

# Specify bypass strategy
scihub-cli papers.txt --bypass cloudscraper

# Target specific mirror (like sci-hub.se)
scihub-cli papers.txt -m https://sci-hub.se --bypass cloudscraper

# With verbose logging and custom output
scihub-cli papers.txt -o downloads -v -r 5
```

### Available Bypass Strategies

- **cloudscraper**: Primary method using cloudscraper library (recommended for sci-hub.se)
- **requests_html**: Fallback using requests-html with JavaScript rendering
- **basic**: Basic requests with stealth headers (last resort)

### Testing
```bash
# Run all tests
python -m unittest discover tests/

# Test against sci-hub.se specifically
echo "10.1038/nature12373" > test.txt
scihub-cli test.txt -m https://sci-hub.se --bypass cloudscraper -v
```

## Implementation Details

### Cloudflare Bypass Strategy

The `CloudflareBypassManager` class implements multiple bypass methods:

1. **Primary**: cloudscraper with optimized browser fingerprinting
2. **Fallback**: requests-html with JavaScript rendering capability
3. **Last Resort**: Basic requests with realistic headers

### Mirror Management

The system intelligently tests mirrors in order:
1. https://sci-hub.se (primary target)
2. https://www.sci-hub.ee (backup)
3. https://sci-hub.ru, sci-hub.ren, sci-hub.wf (additional fallbacks)

### Error Handling

- **403 Errors**: Automatically attempts bypass and retries
- **Challenge Detection**: Identifies Cloudflare challenges and applies appropriate bypass
- **Exponential Backoff**: Smart retry timing to avoid rate limits
- **File Validation**: Checks file sizes and content types

## Configuration

Key settings in `scihub_dl.py`:
- Default mirrors prioritize sci-hub.se
- Timeout: 60 seconds
- Retries: 3 attempts with exponential backoff
- Bypass strategy: cloudscraper (optimized for Cloudflare)

## Success Metrics

The refactored implementation has successfully:
- ✅ Removed complex SeleniumBase dependencies
- ✅ Implemented lightweight cloudscraper-based bypass
- ✅ Maintained compatibility with all mirrors
- ✅ Improved download success rates
- ✅ Preserved metadata extraction and filename generation
- ✅ Added intelligent fallback strategies