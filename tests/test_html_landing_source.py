from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scihub_cli.client import SciHubClient
from scihub_cli.core.downloader import FileDownloader
from scihub_cli.core.source_manager import SourceManager
from scihub_cli.sources.direct_pdf_source import DirectPDFSource
from scihub_cli.sources.html_landing_source import HTMLLandingSource
from scihub_cli.sources.pmc_source import PMCSource


@dataclass
class _StubDownloader:
    html: str
    status: int = 200

    def get_page_content(self, url: str) -> tuple[str | None, int | None]:  # noqa: ARG002
        return self.html, self.status


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
    def __init__(self, url_to_response: dict[str, _FakeResponse]):
        self._url_to_response = url_to_response

    def get(self, url: str, **kwargs):  # noqa: ARG002
        return self._url_to_response.get(
            url, _FakeResponse(b"not found", status_code=404, content_type="text/html")
        )


def test_html_landing_extracts_citation_pdf_meta():
    html = """
    <html><head>
      <meta name="citation_pdf_url" content="/files/paper.pdf" />
    </head><body></body></html>
    """
    source = HTMLLandingSource(downloader=_StubDownloader(html=html))  # type: ignore[arg-type]
    base_url = "https://example.org/article/123"
    assert source.get_pdf_url(base_url) == "https://example.org/files/paper.pdf"


def test_html_landing_extracts_link_type_pdf():
    html = """
    <html><head>
      <link rel="alternate" type="application/pdf" href="paper.pdf" />
    </head><body></body></html>
    """
    source = HTMLLandingSource(downloader=_StubDownloader(html=html))  # type: ignore[arg-type]
    base_url = "https://example.org/article/123/"
    assert source.get_pdf_url(base_url) == "https://example.org/article/123/paper.pdf"


def test_html_landing_picks_best_anchor_pdf():
    html = """
    <html><body>
      <a href="javascript:void(0)">PDF</a>
      <a href="/download">Download</a>
      <a href="/content/paper.pdf">Download PDF</a>
    </body></html>
    """
    source = HTMLLandingSource(downloader=_StubDownloader(html=html))  # type: ignore[arg-type]
    base_url = "https://example.org/article/123/"
    assert source.get_pdf_url(base_url) == "https://example.org/content/paper.pdf"


def test_client_download_from_html_landing_offline(tmp_path: Path):
    landing_url = "https://example.org/article/123"
    pdf_url = "https://example.org/files/paper.pdf"
    html_bytes = f"""
    <html><head><meta name="citation_pdf_url" content="{pdf_url}" /></head><body></body></html>
    """.encode()

    session = _FakeSession(
        {
            landing_url: _FakeResponse(html_bytes, content_type="text/html"),
            pdf_url: _FakeResponse(_make_fake_pdf_bytes(), content_type="application/pdf"),
        }
    )
    downloader = FileDownloader(session=session, timeout=5)  # type: ignore[arg-type]

    sources = [
        DirectPDFSource(),
        PMCSource(downloader=downloader),
        HTMLLandingSource(downloader=downloader),
    ]
    source_manager = SourceManager(sources=sources, enable_year_routing=False)

    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,
    )

    result = client.download_paper(landing_url)
    assert result, "Expected download to succeed for HTML landing page URL"
    assert Path(result).exists()
    assert Path(result).read_bytes()[:4] == b"%PDF"
