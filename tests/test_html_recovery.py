from __future__ import annotations

from pathlib import Path

from scihub_cli.client import SciHubClient
from scihub_cli.core.downloader import FileDownloader
from scihub_cli.core.source_manager import SourceManager
from scihub_cli.sources.direct_pdf_source import DirectPDFSource


def _make_fake_pdf_bytes(size: int = 12000) -> bytes:
    assert size > 4
    header = b"%PDF-1.4\n"
    body = b"0" * (size - len(header) - len(b"\n%%EOF\n"))
    return header + body + b"\n%%EOF\n"


class _FakeResponse:
    def __init__(
        self, content: bytes, status_code: int = 200, content_type: str = "application/pdf"
    ):
        self.status_code = status_code
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(content)),
        }
        self._content = content
        self.text = content.decode("utf-8", errors="replace")

    def iter_content(self, chunk_size: int = 8192):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]


class _FakeSession:
    def __init__(self, url_to_response: dict[str, _FakeResponse]):
        self._url_to_response = url_to_response

    def get(self, url: str, **kwargs):  # noqa: ARG002
        return self._url_to_response.get(
            url, _FakeResponse(b"not found", status_code=404, content_type="text/html")
        )


class _NoBypassDownloader(FileDownloader):
    def _download_with_cloudscraper(self, url, output_path, progress_callback=None):  # noqa: ARG002
        return False, "disabled in test"

    def _download_with_curl_cffi(self, url, output_path, progress_callback=None):  # noqa: ARG002
        return False, "disabled in test"


def test_downloader_recovers_from_html_by_extracting_pdf_candidates(tmp_path: Path):
    entry_url = "https://example.org/paper.pdf"
    recovered_pdf_url = "https://example.org/files/recovered.pdf"
    landing_html = (
        b"<html><body><a href='/files/recovered.pdf'>Download PDF</a></body></html>"
    )

    session = _FakeSession(
        {
            entry_url: _FakeResponse(landing_html, content_type="text/html"),
            recovered_pdf_url: _FakeResponse(_make_fake_pdf_bytes(), content_type="application/pdf"),
        }
    )
    downloader = _NoBypassDownloader(session=session, timeout=5)  # type: ignore[arg-type]
    source_manager = SourceManager(sources=[DirectPDFSource()], enable_year_routing=False)
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,
    )

    result = client.download_paper(entry_url)

    assert result.success
    assert result.file_path
    assert Path(result.file_path).read_bytes()[:4] == b"%PDF"


def test_downloader_html_recovery_failure_reports_extracted_candidates(tmp_path: Path):
    entry_url = "https://example.org/paper.pdf"
    missing_pdf_url = "https://example.org/files/missing.pdf"
    landing_html = b"<html><body><a href='/files/missing.pdf'>Download PDF</a></body></html>"

    session = _FakeSession(
        {
            entry_url: _FakeResponse(landing_html, content_type="text/html"),
            missing_pdf_url: _FakeResponse(b"not found", status_code=404, content_type="text/html"),
        }
    )
    downloader = _NoBypassDownloader(session=session, timeout=5)  # type: ignore[arg-type]
    source_manager = SourceManager(sources=[DirectPDFSource()], enable_year_routing=False)
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,
    )

    result = client.download_paper(entry_url)

    assert not result.success
    assert result.error
    assert "HTML recovery tried 1 extracted candidate URLs" in result.error
    assert missing_pdf_url in result.error
