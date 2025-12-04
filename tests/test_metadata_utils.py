#!/usr/bin/env python3
"""
Tests for the metadata extraction and filename generation functionality.
Updated for multi-source architecture (Sci-Hub + Unpaywall).
"""

import os
import unittest

from scihub_cli.metadata_utils import generate_filename_from_metadata
from scihub_cli.sources.unpaywall_source import UnpaywallSource


class TestMetadataUtils(unittest.TestCase):
    """Tests for metadata extraction and filename generation."""

    def setUp(self):
        """Set up test cases with known DOIs and expected metadata."""
        # Get email for Unpaywall tests
        self.email = os.getenv("SCIHUB_CLI_EMAIL")
        if not self.email:
            from scihub_cli.config.user_config import user_config

            self.email = user_config.get_email()

        # Test cases using Unpaywall (more reliable than Sci-Hub for testing)
        self.test_cases = [
            {
                "doi": "10.1371/journal.pone.0250916",
                "expected_title": "Contrasting impacts",
                "expected_year": "2021",
            },
            {
                "doi": "10.1038/s41467-021-27699-2",
                "expected_title": "Visualizing group II intron",
                "expected_year": "2022",
            },
        ]

    def test_unpaywall_metadata(self):
        """Test metadata retrieval from Unpaywall."""
        if not self.email:
            self.skipTest("No email configured for Unpaywall tests")

        unpaywall = UnpaywallSource(email=self.email)

        for test_case in self.test_cases:
            doi = test_case["doi"]
            metadata = unpaywall.get_metadata(doi)

            # Skip if we couldn't fetch metadata
            if not metadata:
                print(f"Skipping test for {doi} - not found in Unpaywall")
                continue

            # Verify metadata was extracted
            self.assertIsNotNone(metadata, f"Failed to get metadata for {doi}")

            # Verify title (partial match)
            expected_title = test_case["expected_title"]
            self.assertTrue(
                expected_title.lower() in metadata["title"].lower(),
                f"Expected title fragment '{expected_title}' not found in '{metadata['title']}'",
            )

            # Verify year
            expected_year = test_case["expected_year"]
            self.assertEqual(
                expected_year,
                metadata["year"],
                f"Expected year {expected_year} doesn't match {metadata['year']}",
            )

    def test_generate_filename_from_metadata(self):
        """Test filename generation from metadata."""
        test_cases = [
            {
                "title": "Array programming with NumPy",
                "year": "2020",
                "doi": "10.1038/s41586-020-2649-2",
                "expected": "[2020] - Array programming with NumPy.pdf",
            },
            {
                "title": "A very long title that exceeds the maximum length and should be truncated appropriately when generating the filename",
                "year": "2021",
                "doi": "10.1038/s41586-021-03380-y",
                "expected": "[2021] - A very long title that exceeds the maximum length and should be truncated appropriately",
            },
            {
                "title": 'Title with unsafe characters: <>/\\:"|?*',
                "year": "2022",
                "doi": "10.1016/example",
                "expected": "[2022] - Title with unsafe characters_ _________.pdf",
            },
            {
                # Test very short title (should fall back to DOI)
                "title": "A",
                "year": "2023",
                "doi": "10.1016/s1003-6326(21)65629-7",
                "expected": "[2023] - 10.1016_s1003-6326(21)65629-7.pdf",
            },
        ]

        for test_case in test_cases:
            filename = generate_filename_from_metadata(
                test_case["title"], test_case["year"], test_case["doi"]
            )

            # For the long title case, just check if it's truncated
            if "very long title" in test_case["title"]:
                self.assertTrue(len(filename) <= 104)  # 100 chars + '.pdf'
                self.assertTrue(filename.startswith(f"[{test_case['year']}] - "))
                self.assertTrue(filename.endswith(".pdf"))
            else:
                self.assertEqual(
                    test_case["expected"],
                    filename,
                    f"Generated filename '{filename}' doesn't match expected '{test_case['expected']}'",
                )


if __name__ == "__main__":
    unittest.main()
