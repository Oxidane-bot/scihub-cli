from __future__ import annotations

from pathlib import Path

from scihub_cli.client import SciHubClient
from scihub_cli.core.source_manager import SourceManager
from scihub_cli.sources.base import PaperSource
from scihub_cli.sources.direct_pdf_source import DirectPDFSource


def _fake_pdf_bytes(size: int = 12_000) -> bytes:
    header = b"%PDF-1.4\n"
    trailer = b"\n%%EOF\n"
    return header + b"0" * (size - len(header) - len(trailer)) + trailer


class _ExplodingArxivSource(PaperSource):
    @property
    def name(self) -> str:
        return "arXiv"

    def can_handle(self, _identifier: str) -> bool:
        return True

    def get_pdf_url(self, _identifier: str) -> str:
        raise AssertionError("direct arXiv PDF URLs must not query arXiv first")

    def get_metadata(self, _identifier: str) -> dict | None:
        raise AssertionError("direct arXiv PDF URLs must not fetch arXiv metadata first")


class _WritingDownloader:
    def download_file(self, _url: str, output_path: str, progress_callback=None):  # noqa: ARG002
        Path(output_path).write_bytes(_fake_pdf_bytes())
        return True, None


def test_arxiv_pdf_url_uses_direct_download_and_reasonable_filename(tmp_path: Path):
    url = "https://arxiv.org/pdf/1706.03762.pdf"
    manager = SourceManager(
        sources=[DirectPDFSource(), _ExplodingArxivSource()],
        enable_year_routing=False,
    )
    client = SciHubClient(
        output_dir=str(tmp_path),
        downloader=_WritingDownloader(),  # type: ignore[arg-type]
        source_manager=manager,
    )

    result = client.download_paper(url)

    assert result.success
    assert result.source == "Direct PDF"
    assert result.file_path is not None
    assert Path(result.file_path).name == "1706.03762.pdf"
