"""
Abstract base class for paper sources.
"""

from abc import ABC, abstractmethod


class PaperSource(ABC):
    """Abstract base class for all paper sources."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the name of this source (e.g., 'Sci-Hub', 'Unpaywall')."""
        pass

    @abstractmethod
    def can_handle(self, doi: str) -> bool:
        """
        Check if this source can potentially handle the given DOI.

        Args:
            doi: The DOI to check

        Returns:
            True if this source might have the paper, False otherwise
        """
        pass

    @abstractmethod
    def get_pdf_url(self, doi: str) -> str | None:
        """
        Get the direct PDF download URL for a given DOI.

        Args:
            doi: The DOI to look up

        Returns:
            PDF URL if found, None otherwise
        """
        pass

    def get_metadata(self, doi: str) -> dict[str, str] | None:
        """
        Get metadata for a paper (optional, not all sources provide this).

        Args:
            doi: The DOI to look up

        Returns:
            Dictionary with metadata (title, year, etc.) or None
        """
        return None

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.name}>"
