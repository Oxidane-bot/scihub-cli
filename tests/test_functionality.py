#!/usr/bin/env python3
"""
Test script for Sci-Hub CLI functionality with multi-source support
"""

import os
import sys
import tempfile

# Add the scihub_cli module to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scihub_cli.client import SciHubClient
from scihub_cli.core.mirror_manager import MirrorManager


def test_mirrors():
    """Test all mirrors for basic connectivity"""
    print("Testing mirror connectivity...")
    mirror_manager = MirrorManager()

    for mirror in mirror_manager.mirrors:
        try:
            import requests

            response = requests.get(mirror, timeout=10)
            status = (
                "Working" if response.status_code == 200 else f"Failed ({response.status_code})"
            )
            print(f"{mirror}: {status}")
        except Exception as e:
            print(f"{mirror}: Failed ({e})")


def test_download_multi_source():
    """Test download functionality with multiple sources and different years"""
    print("\nTesting multi-source download functionality...")

    # Create temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        # Test requires email for Unpaywall
        email = os.getenv("SCIHUB_CLI_EMAIL")
        if not email:
            # Try to get from config
            from scihub_cli.config.user_config import user_config

            email = user_config.get_email()

        if not email:
            print("WARNING: No email configured, Unpaywall tests will be skipped")
            print("Set SCIHUB_CLI_EMAIL or run 'scihub-cli --email your@email.com' first")
            return

        client = SciHubClient(output_dir=temp_dir, timeout=30, retries=2, email=email)

        # Test cases: different years and sources
        test_cases = [
            {
                "doi": "10.1038/nature12373",
                "year": 2013,
                "description": "Old paper (2013) - should use Sci-Hub first",
                "expected_source": "Sci-Hub",
                "required": False,  # Sci-Hub may be unavailable
            },
            {
                "doi": "10.1371/journal.pone.0250916",
                "year": 2021,
                "description": "Recent paper (2021) - PLOS ONE OA, Unpaywall should work",
                "expected_source": "Unpaywall",
                "required": True,  # OA papers should always work
            },
        ]

        results = []
        for test_case in test_cases:
            doi = test_case["doi"]
            print(f"\nTest: {test_case['description']}")
            print(f"DOI: {doi}")

            result = client.download_paper(doi)
            if result:
                file_size = os.path.getsize(result)
                print(f"SUCCESS: {result} ({file_size} bytes)")

                # Verify PDF header
                with open(result, "rb") as f:
                    header = f.read(4)
                    is_valid_pdf = header == b"%PDF"
                    print(f"Valid PDF: {is_valid_pdf}")
                    assert is_valid_pdf, f"Downloaded file is not a valid PDF: {result}"
                    results.append((True, test_case["required"]))
            else:
                print("FAILED: Could not download")
                # Only fail the test if this was a required download
                if test_case["required"]:
                    results.append((False, True))
                else:
                    print("(Non-critical failure - source may be temporarily unavailable)")
                    results.append((False, False))

        # Check that all required downloads succeeded
        required_results = [success for success, required in results if required]

        success_count = sum(success for success, _ in results)
        required_count = len(required_results)
        required_success = sum(required_results)

        print(f"\n{success_count}/{len(results)} downloads completed")
        print(f"Required: {required_success}/{required_count}")

        assert all(
            required_results
        ), f"Required downloads failed: {required_success}/{required_count} successful"


def test_metadata_extraction():
    """Test metadata extraction from Sci-Hub pages"""
    print("\nTesting metadata extraction...")

    from scihub_cli.metadata_utils import generate_filename_from_metadata

    # This would require fetching HTML from Sci-Hub, which we'll simulate
    print("Metadata extraction functions are available")

    # Test filename generation
    test_filename = generate_filename_from_metadata(
        "Array programming with NumPy", "2020", "10.1038/s41586-020-2649-2"
    )
    expected = "[2020] - Array programming with NumPy.pdf"

    print(f"Generated filename: {test_filename}")
    assert test_filename == expected, f"Expected {expected}, got {test_filename}"


if __name__ == "__main__":
    print("Sci-Hub CLI Test Suite")
    print("=" * 70)

    # Run tests
    test_mirrors()

    metadata_ok = test_metadata_extraction()
    download_ok = test_download_multi_source()

    print("\n" + "=" * 70)
    print("Test Summary:")
    print(f"Metadata extraction: {'PASS' if metadata_ok else 'FAIL'}")
    if download_ok is None:
        print("Multi-source download: SKIPPED (no email configured)")
    else:
        print(f"Multi-source download: {'PASS' if download_ok else 'FAIL'}")

    if metadata_ok and download_ok:
        print("\nAll tests passed!")
        sys.exit(0)
    elif download_ok is None:
        print("\nSome tests skipped")
        sys.exit(0)
    else:
        print("\nSome tests failed")
        sys.exit(1)
