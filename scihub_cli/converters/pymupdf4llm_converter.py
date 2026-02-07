"""pymupdf4llm-based PDF -> Markdown converter.

This module intentionally imports `pymupdf4llm` lazily inside `convert()` so
that the base downloader can run without the optional markdown dependencies.
"""

from __future__ import annotations

from pathlib import Path

from .pdf_to_md import MarkdownConvertOptions


class Pymupdf4llmConverter:
    """Convert PDF to Markdown using pymupdf4llm."""

    def convert(
        self, pdf_path: str, md_path: str, *, options: MarkdownConvertOptions
    ) -> tuple[bool, str | None]:
        try:
            import pymupdf4llm  # type: ignore
        except Exception as e:  # pragma: no cover
            return False, f"pymupdf4llm is not installed: {e}"

        try:
            markdown_text = pymupdf4llm.to_markdown(pdf_path)
        except Exception as e:
            return False, str(e)

        try:
            output_path = Path(md_path)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            if output_path.exists() and not options.overwrite:
                return True, None
            output_path.write_text(markdown_text or "", encoding="utf-8")
        except Exception as e:
            return False, f"Failed to write markdown: {e}"

        return True, None
