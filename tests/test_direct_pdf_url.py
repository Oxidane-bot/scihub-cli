from pathlib import Path

from scihub_cli.client import SciHubClient
from scihub_cli.core.downloader import FileDownloader
from scihub_cli.core.source_manager import SourceManager
from scihub_cli.sources.direct_pdf_source import DirectPDFSource
from scihub_cli.sources.pmc_source import PMCSource


def _make_fake_pdf_bytes(size: int = 12000) -> bytes:
    assert size > 4
    header = b"%PDF-1.4\n"
    body = b"0" * (size - len(header) - len(b"\n%%EOF\n"))
    return header + body + b"\n%%EOF\n"


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200, content_type: str = "application/pdf"):
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        self._content = content
        self.text = content.decode("utf-8", errors="replace")

    def iter_content(self, chunk_size: int = 8192):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]


class _FakeSession:
    def __init__(self, url_to_content: dict[str, bytes]):
        self._url_to_content = url_to_content

    def get(self, url: str, **kwargs):  # noqa: ARG002
        content = self._url_to_content.get(url)
        if content is None:
            return _FakeResponse(b"not found", status_code=404, content_type="text/html")
        return _FakeResponse(content)


def test_download_direct_pdf_url_offline(tmp_path: Path):
    url = "https://files.eric.ed.gov/fulltext/EJ1358705.pdf"
    content = _make_fake_pdf_bytes()
    session = _FakeSession({url: content})
    downloader = FileDownloader(session=session, timeout=5)  # type: ignore[arg-type]

    sources = [DirectPDFSource(), PMCSource(downloader=downloader)]
    source_manager = SourceManager(sources=sources, enable_year_routing=False)

    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,
    )

    result = client.download_paper(url)
    assert result, "Expected download to succeed for direct PDF URL"
    assert Path(result).name == "EJ1358705.pdf"

    data = Path(result).read_bytes()
    assert data[:4] == b"%PDF"
    assert len(data) >= 10000
