"""Shared interfaces for PDF -> Markdown conversion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class MarkdownConvertOptions:
    """Options for markdown conversion."""

    overwrite: bool = False


class PdfToMarkdownConverter(Protocol):
    """Interface for converting a PDF file into Markdown."""

    def convert(
        self, pdf_path: str, md_path: str, *, options: MarkdownConvertOptions
    ) -> tuple[bool, str | None]:
        """Convert pdf_path to md_path.

        Returns:
            (success, error_message)
        """

