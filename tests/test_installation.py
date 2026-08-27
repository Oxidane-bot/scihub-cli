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
    """Test the CLI through the interpreter running this test suite.

    Invoking the module avoids relying on a shell PATH that may not include the
    environment where the package was installed (for example, a CI venv).
    """
    print("\nTesting command availability through the active interpreter...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "scihub_cli", "--version"],
            capture_output=True,
            text=True,
            check=True,
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
