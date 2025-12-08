# Sci-Hub CLI

A command-line tool for batch downloading academic papers with multi-source support (Sci-Hub, Unpaywall, arXiv, CORE).

*Read this in other languages: [English](README.md), [简体中文](README.zh-CN.md)*

## Features

- **Multi-Source Support**: Intelligently routes downloads across multiple sources
  - **arXiv**: Prioritized for preprints (free, no API key needed)
  - **Unpaywall**: For open access papers (requires email)
  - **Sci-Hub**: Comprehensive fallback (85%+ coverage)
  - **CORE**: Additional OA fallback
- **Smart Year-Based Routing**:
  - Papers before 2021: Sci-Hub first (better historical coverage)
  - Papers 2021+: Unpaywall/arXiv first (better for recent OA papers)
- **Smart Fallback**: Automatically tries alternative sources if primary fails
- **Flexible Input**: Download papers using DOIs, arXiv IDs, or URLs
- Batch processing from a text file
- Automatic mirror selection and testing
- Customizable output directory
- Robust error handling and retries
- PDF validation (rejects HTML files)
- Progress reporting
- **Metadata-based Filenames**: Automatically names files as `[YYYY] - [Title].pdf` for easy organization

## Installation

[uv](https://docs.astral.sh/uv/) is an extremely fast Python package and project manager, written in Rust.

### Install uv

```bash
# macOS and Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

# Or via pip
pip install uv
```

### Install scihub-cli (Global Installation)

```bash
# Install globally from the current directory
uv tool install .

# Or install globally from GitHub
uv tool install git+https://github.com/Oxidane-bot/scihub-cli.git

# Try without installing (temporary run)
uvx scihub-cli papers.txt
```

**Note**: `uv tool install` installs the tool globally on your system, making the `scihub-cli` command available from anywhere in your terminal.

### Global vs Temporary Usage

- **Global Installation**: Use `uv tool install` to install the tool permanently on your system
- **Temporary Usage**: Use `uvx scihub-cli` to run the tool without installing it
- **Source Code**: Clone the repo and run directly with Python for development

### Manual Installation (Alternative)

If you prefer to run directly from source:

1. Clone this repository:
   ```
   git clone https://github.com/Oxidane-bot/scihub-cli.git
   cd scihub-cli
   ```

2. Install the required dependencies:
   ```
   pip install -r requirements.txt
   ```

3. Run directly with Python:
   ```
   python -m scihub_cli.scihub_dl input_file.txt
   ```

### Troubleshooting Installation

If you encounter issues with the installation, try the following:

1. Ensure you have Python 3.9+ installed:
   ```bash
   python --version
   ```

2. Verify uv is installed correctly:
   ```bash
   uv --version
   ```

3. Check if the command is in your PATH:
   ```bash
   # On Windows
   where scihub-cli
   
   # On macOS/Linux
   which scihub-cli
   ```

4. If you get "command not found" errors after installation:
   ```bash
   # Update shell environment
   uv tool update-shell
   
   # Manual PATH refresh
   # On Windows
   $env:Path = [System.Environment]::GetEnvironmentVariable("Path","User")
   
   # On macOS/Linux
   source ~/.bashrc  # or .zshrc, .bash_profile, etc.
   ```

5. If having issues, try:
   ```bash
   # List installed tools
   uv tool list
   
   # Upgrade a tool
   uv tool upgrade scihub-cli
   
   # Reinstall
   uv tool uninstall scihub-cli
   uv tool install scihub-cli
   ```

## Usage

### Basic Usage

```bash
# If installed with uv
scihub-cli input_file.txt

# If running temporarily with uv
uvx scihub-cli input_file.txt

# If running directly from source
python -m scihub_cli.scihub_dl input_file.txt
```

Where `input_file.txt` is a text file containing DOIs or paper URLs, one per line.

### Input File Format

Create a text file with one identifier per line. Supports:
- **DOIs**: `10.1038/nature12373`
- **arXiv IDs**: `2301.12345` or `arxiv:2401.00001`
- **URLs**: `https://doi.org/10.1126/science.abc1234`

Example `papers.txt`:
```
# Comments start with a hash symbol
10.1038/s41586-020-2649-2
2301.12345
arxiv:2401.00001
https://www.nature.com/articles/s41586-021-03380-y
10.1016/s1003-6326(21)65629-7
```

### Optional Email (Unpaywall)

Set an email if you want Unpaywall open-access lookup. If no email is provided, Unpaywall is skipped automatically.

```bash
# Enable Unpaywall by setting email
scihub-cli papers.txt --email your-email@university.edu
```

The email is saved to `~/.scihub-cli/config.json` and sent only to Unpaywall for rate limiting (not tracking).

### Command-Line Options

```
usage: scihub-cli [-h] [-o OUTPUT] [-m MIRROR] [-t TIMEOUT] [-r RETRIES] [-p PARALLEL]
                  [--email EMAIL] [-v] [--version] input_file

Download academic papers from Sci-Hub and Unpaywall in batch mode.

positional arguments:
  input_file            Text file containing DOIs or URLs (one per line)

options:
  -h, --help            show this help message and exit
  -o OUTPUT, --output OUTPUT
                        Output directory for downloaded PDFs (default: ./downloads)
  -m MIRROR, --mirror MIRROR
                        Specific Sci-Hub mirror to use
  -t TIMEOUT, --timeout TIMEOUT
                        Request timeout in seconds (default: 30)
  -r RETRIES, --retries RETRIES
                        Number of retries for failed downloads (default: 3)
  -p PARALLEL, --parallel PARALLEL
                        Reserved; downloads are processed sequentially
  --email EMAIL         Email for Unpaywall API (saves to config file)
  -v, --verbose         Enable verbose logging
  --version             show program's version number and exit
```

### Configuration

scihub-cli stores configuration in `~/.scihub-cli/config.json`:

```json
{
  "email": "your-email@university.edu"
}
```

You can edit this file directly or use `--email` to update it.

### Examples

```bash
# Basic usage
scihub-cli papers.txt

# Specify output directory
scihub-cli -o research/papers papers.txt

# Use specific mirror
scihub-cli -m https://sci-hub.se papers.txt

# Increase verbosity
scihub-cli -v papers.txt
```

## How It Works

The tool uses intelligent multi-source routing:

1. **Year Detection**: Queries Crossref API to determine publication year
2. **Smart Routing**:
   - Papers before 2021 → Try Sci-Hub first, then Unpaywall
   - Papers 2021+ → Try Unpaywall first, then Sci-Hub
   - Unknown year → Try Unpaywall first (conservative)
3. **Download Process**:
   - Get PDF URL from selected source
   - Download with progress tracking
   - Validate PDF (reject HTML files)
   - Generate filename from metadata: `[YYYY] - [Title].pdf`

### Why Multi-Source?

- **Sci-Hub**: Excellent for pre-2021 papers (85%+ coverage), but stopped updating in 2020
- **Unpaywall**: Best for 2021+ open access papers (25-35% coverage for recent papers)
- **Combined**: Achieves ~75-80% overall success rate vs ~70% with Sci-Hub alone

### Domain-Specific User-Agents

The tool automatically adapts HTTP headers for different publishers:
- **MDPI**: Uses `curl/8.0.0` (required by their CDN)
- **Others**: Uses browser User-Agent for compatibility

## Coverage and Success Rates

| Year Range | Primary Source | Success Rate |
|-----------|---------------|--------------|
| Before 2021 | Sci-Hub | 85-90% |
| 2021+ | Unpaywall | 25-35% |
| Overall | Multi-source | 75-80% |

## Limitations

- Not all papers are available through Sci-Hub or Unpaywall
- Unpaywall only covers open access papers
- Some publishers may block automated downloads
- Sci-Hub mirrors may change or become unavailable

## Legal Disclaimer

This tool is provided for educational and research purposes only. Users are responsible for ensuring they comply with applicable laws and regulations when using this tool.

## Testing

The project includes comprehensive tests for multi-source functionality:

### Running Tests

```bash
# Run all tests
cd tests
uv run python test_functionality.py
uv run python -m unittest test_metadata_utils.py -v

# Or run all unit tests
uv run python -m unittest discover -v
```

### Test Coverage

The test suite covers:

- ✅ **Multi-Source Download**: Tests year-based routing (2013 paper via Sci-Hub, 2021 via Unpaywall)
- ✅ **PDF Validation**: Verifies downloaded files have valid PDF headers
- ✅ **Mirror Connectivity**: Tests all Sci-Hub mirrors for accessibility
- ✅ **Metadata Extraction**: Tests Unpaywall API metadata retrieval
- ✅ **Filename Generation**: Tests filename sanitization and edge cases

### Recent Test Results

```
Multi-source download: 2/2 PASS
- 2013 paper (944 KB) via Sci-Hub ✓
- 2021 paper (1.6 MB) via Unpaywall ✓
PDF validation: All valid ✓
Metadata extraction: PASS ✓
```

## License

This project is licensed under the MIT License - see the LICENSE file for details. 
