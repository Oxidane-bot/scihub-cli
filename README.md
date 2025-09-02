# Sci-Hub CLI

A command-line tool for batch downloading academic papers from Sci-Hub.

*Read this in other languages: [English](README.md), [简体中文](README.zh-CN.md)*

## Features

- Download papers using DOIs or URLs
- Batch processing from a text file
- Automatic mirror selection
- Customizable output directory
- Proper error handling and retries
- Progress reporting
- **Metadata-based Filenames:** Attempts to name downloaded PDF files using the article's metadata (e.g., `[YYYY] - [Sanitized Title].pdf`). This makes files more descriptive and easier to organize. If metadata cannot be extracted, it falls back to the previous naming scheme (based on DOI or input identifier).

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

```
# Comments start with a hash symbol
10.1038/s41586-020-2649-2
https://www.nature.com/articles/s41586-021-03380-y
10.1016/s1003-6326(21)65629-7
```

### Command-Line Options

```
usage: scihub-cli [-h] [-o OUTPUT] [-m MIRROR] [-t TIMEOUT] [-r RETRIES] [-p PARALLEL] [-v] [--version] input_file

Download academic papers from Sci-Hub in batch mode.

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
                        Number of parallel downloads (default: 3)
  -v, --verbose         Enable verbose logging
  --version             show program's version number and exit
```

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

The tool works by:

1. Reading the input file and extracting DOIs/URLs
2. For each DOI/URL:
   - Accessing Sci-Hub to get the paper page
   - Extracting the direct download link
   - Downloading the PDF file
   - Saving it to the output directory

## Limitations

- Not all papers may be available on Sci-Hub
- Sci-Hub mirrors may change or become unavailable
- The tool respects Sci-Hub's website structure which may change over time

## Legal Disclaimer

This tool is provided for educational and research purposes only. Users are responsible for ensuring they comply with applicable laws and regulations when using this tool.

## Testing

The project includes comprehensive tests to ensure functionality works correctly:

### Running Tests

```bash
# Run all tests
python tests/test_functionality.py
python tests/test_metadata_utils.py
python tests/test_installation.py

# Run tests with verbose output
python -m pytest tests/ -v
```

### Test Results

The test suite covers:
- ✅ **Mirror Connectivity**: Tests all Sci-Hub mirrors for accessibility
- ✅ **Download Functionality**: Tests actual paper downloads with real DOIs
- ✅ **Metadata Extraction**: Tests paper metadata parsing and filename generation
- ✅ **Installation**: Verifies proper package installation and CLI availability

### Test Coverage

- **Functionality Tests**: Mirror connectivity, download success, error handling
- **Metadata Tests**: Title extraction, author parsing, filename generation
- **Installation Tests**: Package import, command availability, version checking

## License

This project is licensed under the MIT License - see the LICENSE file for details. 