"""
Sci-Hub metadata utilities for extracting article metadata (title and year)
and generating filenames based on that metadata.
"""

import re

from bs4 import BeautifulSoup


def extract_metadata(html_content: str) -> dict or None:  # type: ignore
    """
    Extract metadata (title and year) from Sci-Hub article HTML.

    Args:
        html_content (str): The full HTML content of a Sci-Hub article page.

    Returns:
        dict or None: A dictionary containing 'title' and 'year' if successful,
                     None if extraction fails.
    """
    if not html_content:
        return None

    try:
        soup = BeautifulSoup(html_content, "html.parser")

        # Find the citation div which contains both the year and title
        citation_div = soup.find("div", id="citation")
        if not citation_div:
            return None

        # Extract citation text
        citation_text = citation_div.get_text()

        # Extract year using regex - looking for (YYYY) pattern
        year_match = re.search(r"\((\d{4})\)", citation_text)
        year = year_match.group(1) if year_match else None

        # Handle different citation formats
        # Some citations have the title in an <i> tag, others have inconsistent structures
        title = None

        # Try to extract the title from an <i> tag if present
        title_elem = citation_div.find("i")
        if title_elem and len(title_elem.get_text()) > 10:  # Ensure it's a substantial text
            title_text = title_elem.get_text()

            # Clean up the title - remove everything after period+space or period+journal name
            # This handles formats like "Title. Journal, Vol..."
            title_parts = title_text.split(". ", 1)
            title = title_parts[0]

            # If no period found, look for other common delimiters
            if len(title_parts) == 1 and "," in title_text:
                title = title_text.split(",", 1)[0]

        # If title is still None or too short, try alternate extraction method
        if not title or len(title) < 10:
            # Try to find title after year in citation text
            if year and f"({year})" in citation_text:
                # Split after the year
                after_year_parts = citation_text.split(f"({year})", 1)
                if len(after_year_parts) > 1:
                    after_year = after_year_parts[1].strip()

                    # For the specific case where title follows "). " pattern
                    if after_year.startswith(")."):
                        title_candidate = after_year[2:].strip()
                        # Extract everything until the next delimiter
                        for delimiter in [". ", ", "]:
                            if delimiter in title_candidate:
                                title = title_candidate.split(delimiter, 1)[0].strip()
                                break
                        else:
                            title = title_candidate
                    else:
                        # Try other common patterns
                        for delimiter in [". ", ", ", ". doi:", ". DOI:"]:
                            if delimiter in after_year:
                                title = after_year.split(delimiter, 1)[0].strip()
                                break

            # If still no title, try extracting from raw html using regex
            if not title or len(title) < 10:
                # Look for title patterns in the citation div's HTML
                citation_html = str(citation_div)
                title_patterns = [
                    r"\)\.\s*([^\.]+)\.",  # Matches text after "). " and before next "."
                    r"\)\s*([^\.]+)\.",  # Matches text after ")" and before next "."
                    r">\s*([^<>\.]+)\.",  # Matches text between ">" and "."
                ]

                for pattern in title_patterns:
                    matches = re.search(pattern, citation_html)
                    if matches and len(matches.group(1).strip()) > 10:
                        title = matches.group(1).strip()
                        break

        # Return None if either title or year is missing
        if not title or not year:
            return None

        # Additional cleaning for title
        # Remove any HTML tags that might remain
        title = re.sub(r"<[^>]+>", "", title)

        return {"title": title.strip(), "year": year}

    except Exception as e:
        print(f"Error extracting metadata: {e}")
        return None


def generate_filename_from_metadata(title: str, year: str, original_identifier: str) -> str:
    """
    Generate a filename from article metadata.

    Args:
        title (str): The article title.
        year (str): The publication year.
        original_identifier (str): The original identifier (DOI or URL) for fallback.

    Returns:
        str: A sanitized filename in format "[YYYY] - [Title].pdf"
    """
    # Sanitize the title (remove unsafe characters)
    unsafe_chars = r'[<>:"/\\|?*]'
    safe_title = re.sub(unsafe_chars, "_", title)

    # Trim to reasonable length
    if len(safe_title) > 80:
        safe_title = safe_title[:80].rstrip() + "..."

    # Handle edge cases
    if not safe_title or len(safe_title) < 5:
        # Use original identifier as fallback
        safe_identifier = re.sub(unsafe_chars, "_", original_identifier)
        filename = f"[{year}] - {safe_identifier}"
    else:
        filename = f"[{year}] - {safe_title}"

    # Ensure the filename is not too long
    if len(filename) > 100:
        filename = filename[:100]

    return f"{filename}.pdf"
