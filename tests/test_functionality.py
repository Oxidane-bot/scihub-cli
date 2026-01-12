#!/usr/bin/env python3
"""
Test script for Sci-Hub CLI functionality with multi-source support
"""

import os
import sys
import tempfile

import pytest

# Add the scihub_cli module to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scihub_cli.client import SciHubClient
from scihub_cli.core.mirror_manager import MirrorManager
from scihub_cli.core.source_manager import SourceManager
from scihub_cli.sources.arxiv_source import ArxivSource
from scihub_cli.sources.core_source import CORESource
from scihub_cli.sources.unpaywall_source import UnpaywallSource


def _allow_scihub_tests() -> bool:
    return os.getenv("SCIHUB_CLI_ALLOW_SCIHUB", "").lower() in {"1", "true", "yes"}


def _network_tests_enabled() -> bool:
    return os.getenv("SCIHUB_CLI_RUN_NETWORK_TESTS", "").lower() in {"1", "true", "yes"}


@pytest.mark.skipif(
    not _allow_scihub_tests(),
    reason="Sci-Hub integration tests are opt-in via SCIHUB_CLI_ALLOW_SCIHUB=1",
)
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
    if not _network_tests_enabled():
        pytest.skip("Network download test is opt-in via SCIHUB_CLI_RUN_NETWORK_TESTS=1")

    # Create temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        # Test requires email for Unpaywall
        email = os.getenv("SCIHUB_CLI_EMAIL")
        if not email:
            # Try to get from config
            from scihub_cli.config.user_config import user_config

            email = user_config.get_email()

        if not email:
            pytest.skip(
                "No email configured for Unpaywall tests. Set SCIHUB_CLI_EMAIL or run "
                "'scihub-cli --email your@email.com' first."
            )

        # Avoid contacting Sci-Hub by default: construct an OA-only source manager.
        sources = [
            ArxivSource(timeout=30),
            CORESource(api_key=None, timeout=30),
        ]
        sources.insert(0, UnpaywallSource(email=email, timeout=30))

        source_manager = SourceManager(
            sources=sources, year_threshold=2021, enable_year_routing=False
        )
        client = SciHubClient(
            output_dir=temp_dir, timeout=30, retries=2, email=email, source_manager=source_manager
        )

        test_cases = [
            {
                "doi": "10.1371/journal.pone.0250916",
                "description": "OA paper (PLOS ONE) via Unpaywall",
            }
        ]

        results = []
        for test_case in test_cases:
            doi = test_case["doi"]
            print(f"\nTest: {test_case['description']}")
            print(f"DOI: {doi}")

            result = client.download_paper(doi)
            if result.success:
                assert result.file_path
                file_size = os.path.getsize(result.file_path)
                print(f"SUCCESS: {result.file_path} ({file_size} bytes)")

                # Verify PDF header
                with open(result.file_path, "rb") as f:
                    header = f.read(4)
                    is_valid_pdf = header == b"%PDF"
                    print(f"Valid PDF: {is_valid_pdf}")
                    assert is_valid_pdf, f"Downloaded file is not a valid PDF: {result.file_path}"
                results.append(True)
            else:
                print(f"FAILED: {result.error}")
                results.append(False)

        assert all(results), f"OA downloads failed: {sum(results)}/{len(results)} successful"

        print(f"\n{sum(results)}/{len(results)} downloads completed")


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
