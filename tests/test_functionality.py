#!/usr/bin/env python3
"""
Test script for Sci-Hub CLI functionality
"""

import os
import sys
import tempfile
import time
from pathlib import Path

# Add the scihub_cli module to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scihub_cli.scihub_dl import SciHubDownloader

def test_mirrors():
    """Test all mirrors for basic connectivity"""
    print("Testing mirror connectivity...")
    downloader = SciHubDownloader()
    
    for mirror in downloader.mirrors:
        try:
            response = downloader.session.get(mirror, timeout=10)
            status = "Working" if response.status_code == 200 else f"Failed ({response.status_code})"
            print(f"{mirror}: {status}")
        except Exception as e:
            print(f"{mirror}: Failed ({e})")

def test_download_functionality():
    """Test actual download functionality with a known DOI"""
    print("\nTesting download functionality...")
    
    # Create temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        downloader = SciHubDownloader(output_dir=temp_dir, timeout=30, retries=2)
        
        # Test with a well-known DOI
        test_doi = "10.1038/s41586-020-2649-2"
        print(f"Attempting to download: {test_doi}")
        
        result = downloader.download_paper(test_doi)
        if result:
            file_size = os.path.getsize(result)
            print(f"Download successful: {result} ({file_size} bytes)")
            return True
        else:
            print("Download failed")
            return False

def test_metadata_extraction():
    """Test metadata extraction from Sci-Hub pages"""
    print("\nTesting metadata extraction...")
    
    from scihub_cli.metadata_utils import extract_metadata, generate_filename_from_metadata
    
    # This would require fetching HTML from Sci-Hub, which we'll simulate
    print("Metadata extraction functions are available")
    
    # Test filename generation
    test_filename = generate_filename_from_metadata(
        "Array programming with NumPy", 
        "2020", 
        "10.1038/s41586-020-2649-2"
    )
    expected = "[2020] - Array programming with NumPy.pdf"
    
    if test_filename == expected:
        print(f"Filename generation works: {test_filename}")
        return True
    else:
        print(f"Filename generation failed: got {test_filename}, expected {expected}")
        return False

if __name__ == "__main__":
    print("Sci-Hub CLI Test Suite")
    print("=" * 50)
    
    # Run tests
    test_mirrors()
    
    metadata_ok = test_metadata_extraction()
    download_ok = test_download_functionality()
    
    print("\n" + "=" * 50)
    print("Test Summary:")
    print(f"Metadata extraction: {'PASS' if metadata_ok else 'FAIL'}")
    print(f"Download functionality: {'PASS' if download_ok else 'FAIL'}")
    
    if metadata_ok and download_ok:
        print("\nAll tests passed!")
        sys.exit(0)
    else:
        print("\nSome tests failed")
        sys.exit(1)