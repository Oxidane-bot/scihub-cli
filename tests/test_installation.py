#!/usr/bin/env python3
"""
Test script to verify scihub-cli installation.
"""

import subprocess
import sys


def test_import():
    """Test importing the package."""
    print("Testing import...")
    try:
        import scihub_cli

        print(f"Successfully imported scihub_cli version {scihub_cli.__version__}")
    except ImportError as e:
        raise AssertionError(f"Failed to import scihub_cli: {e}") from e


def test_command():
    """Test running the command."""
    print("\nTesting command availability...")
    try:
        result = subprocess.run(
            ["scihub-cli", "--version"], capture_output=True, text=True, check=True
        )
        print(f"Command available: {result.stdout.strip()}")
    except subprocess.CalledProcessError as e:
        raise AssertionError(f"Command failed: {e}\nError output: {e.stderr}") from e
    except FileNotFoundError as e:
        raise AssertionError(
            f"Command not found: {e}. Make sure the package is installed and the script is in your PATH."
        ) from e


if __name__ == "__main__":
    print("Testing scihub-cli installation...\n")

    import_success = test_import()
    command_success = test_command()

    if import_success and command_success:
        print("\n✓ All tests passed! scihub-cli is correctly installed.")
        sys.exit(0)
    else:
        print("\n✗ Some tests failed. Please check the installation.")
        sys.exit(1)
