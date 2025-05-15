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

## Installation

### Option 1: Using pipx (Recommended)

[pipx](https://pypa.github.io/pipx/) allows you to install and run Python applications in isolated environments.

1. Install pipx if you haven't already:
   ```
   # On Windows
   pip install pipx
   pipx ensurepath
   
   # On macOS
   brew install pipx
   pipx ensurepath
   
   # On Linux
   python3 -m pip install --user pipx
   python3 -m pipx ensurepath
   ```

2. Install scihub-cli using pipx:
   ```
   # Install from the current directory
   pipx install .
   
   # Or from GitHub
   pipx install git+https://github.com/Oxidane-bot/scihub-cli.git
   ```

### Option 2: Manual Installation

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
   ```
   python --version
   ```

2. Verify pipx is installed correctly:
   ```
   pipx --version
   ```

3. Check if the command is in your PATH:
   ```
   # On Windows
   where scihub-cli
   
   # On macOS/Linux
   which scihub-cli
   ```

4. If you get "command not found" errors after installation, try:
   ```
   # On Windows
   $env:Path = [System.Environment]::GetEnvironmentVariable("Path","User")
   
   # On macOS/Linux
   source ~/.bashrc  # or .zshrc, .bash_profile, etc.
   ```

## Usage

### Basic Usage

```bash
# If installed with pipx
scihub-cli input_file.txt

# If running directly
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

## License

This project is licensed under the MIT License - see the LICENSE file for details. 