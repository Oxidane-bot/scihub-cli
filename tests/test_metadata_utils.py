#!/usr/bin/env python3
"""
Tests for the metadata extraction and filename generation functionality.
"""

import unittest
import requests

from scihub_cli.metadata_utils import extract_metadata, generate_filename_from_metadata

# Test Sci-Hub mirror to use for fetching test pages
TEST_MIRROR = "https://sci-hub.se"

class TestMetadataUtils(unittest.TestCase):
    """Tests for metadata extraction and filename generation."""
    
    def setUp(self):
        """Set up test cases with known DOIs and expected metadata."""
        self.test_cases = [
            {
                'doi': '10.1038/s41586-020-2649-2',
                'expected_title': 'Array programming with NumPy',
                'expected_year': '2020'
            },
            {
                'doi': '10.1038/s41586-021-03380-y',
                'expected_title': 'People systematically overlook subtractive changes',
                'expected_year': '2021'
            },
            {
                'doi': '10.1016/s1003-6326(21)65629-7',
                'expected_title': 'Effect of Al addition on microstructure and mechanical properties of Mg−Zn−Sn−Mn alloy',
                'expected_year': '2021'
            }
        ]
        
        # Cache for HTML content to avoid repeated downloads during tests
        self.html_cache = {}
        
    def get_html_content(self, doi):
        """
        Fetch HTML content for a given DOI from Sci-Hub.
        
        Args:
            doi (str): The DOI to fetch.
            
        Returns:
            str: The HTML content if successful, None otherwise.
        """
        if doi in self.html_cache:
            return self.html_cache[doi]
            
        try:
            # Configure session with headers to avoid blocking
            session = requests.Session()
            session.headers.update({
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            })
            
            # Construct Sci-Hub URL
            url = f"{TEST_MIRROR}/{doi}"
            response = session.get(url, timeout=30)
            
            if response.status_code == 200:
                self.html_cache[doi] = response.text
                return response.text
            else:
                print(f"Failed to fetch HTML for {doi}: {response.status_code}")
                return None
        except Exception as e:
            print(f"Error fetching HTML for {doi}: {e}")
            return None
    
    def test_extract_metadata(self):
        """Test metadata extraction from Sci-Hub pages."""
        for test_case in self.test_cases:
            doi = test_case['doi']
            html_content = self.get_html_content(doi)
            
            # Skip if we couldn't fetch the content
            if not html_content:
                print(f"Skipping test for {doi} due to fetch failure")
                continue
                
            metadata = extract_metadata(html_content)
            
            # Verify metadata was extracted
            self.assertIsNotNone(metadata, f"Failed to extract metadata for {doi}")
            
            # Verify title
            expected_title = test_case['expected_title']
            self.assertTrue(
                expected_title.lower() in metadata['title'].lower(),
                f"Expected title '{expected_title}' not found in extracted title '{metadata['title']}'"
            )
            
            # Verify year
            expected_year = test_case['expected_year']
            self.assertEqual(
                expected_year, 
                metadata['year'],
                f"Expected year {expected_year} doesn't match extracted year {metadata['year']}"
            )
    
    def test_generate_filename_from_metadata(self):
        """Test filename generation from metadata."""
        test_cases = [
            {
                'title': 'Array programming with NumPy',
                'year': '2020',
                'doi': '10.1038/s41586-020-2649-2',
                'expected': '[2020] - Array programming with NumPy.pdf'
            },
            {
                'title': 'A very long title that exceeds the maximum length and should be truncated appropriately when generating the filename',
                'year': '2021',
                'doi': '10.1038/s41586-021-03380-y',
                'expected': '[2021] - A very long title that exceeds the maximum length and should be truncated appropriately'
            },
            {
                'title': 'Title with unsafe characters: <>/\\:"|?*',
                'year': '2022',
                'doi': '10.1016/example',
                'expected': '[2022] - Title with unsafe characters_ _________.pdf'
            },
            {
                # Test very short title (should fall back to DOI)
                'title': 'A',
                'year': '2023',
                'doi': '10.1016/s1003-6326(21)65629-7',
                'expected': '[2023] - 10.1016_s1003-6326(21)65629-7.pdf'
            }
        ]
        
        for test_case in test_cases:
            filename = generate_filename_from_metadata(
                test_case['title'],
                test_case['year'],
                test_case['doi']
            )
            
            # For the long title case, just check if it's truncated
            if 'very long title' in test_case['title']:
                self.assertTrue(len(filename) <= 104)  # 100 chars + '.pdf'
                self.assertTrue(filename.startswith(f"[{test_case['year']}] - "))
                self.assertTrue(filename.endswith('.pdf'))
            else:
                self.assertEqual(
                    test_case['expected'],
                    filename,
                    f"Generated filename '{filename}' doesn't match expected '{test_case['expected']}'"
                )

if __name__ == '__main__':
    unittest.main()