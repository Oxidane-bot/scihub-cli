from __future__ import annotations

from pathlib import Path

from scihub_cli.client import SciHubClient
from scihub_cli.converters.pdf_to_md import MarkdownConvertOptions
from scihub_cli.core.downloader import FileDownloader
from scihub_cli.core.source_manager import SourceManager
from scihub_cli.models import DownloadProgress
from scihub_cli.sources.base import PaperSource
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
    def __init__(self, url_to_content: dict[str, bytes]):
        self._url_to_content = url_to_content

    def get(self, url: str, **kwargs):  # noqa: ARG002
        content = self._url_to_content.get(url)
        if content is None:
            return _FakeResponse(b"not found", status_code=404, content_type="text/html")
        return _FakeResponse(content)


class _StubSource(PaperSource):
    @property
    def name(self) -> str:
        return "Unpaywall"

    def can_handle(self, doi: str) -> bool:  # noqa: ARG002
        return True

    def get_pdf_url(self, doi: str) -> str | None:  # noqa: ARG002
        return "https://example.org/paper.pdf"

    def get_metadata(self, doi: str) -> dict[str, str]:  # noqa: ARG002
        return {"title": "Example Title", "year": 2020}


class _CoreFallbackSource(PaperSource):
    def __init__(
        self,
        *,
        primary_url: str,
        source_fulltext_urls: list[str] | None = None,
        links_download_urls: list[str] | None = None,
    ):
        self.primary_url = primary_url
        self.source_fulltext_urls = source_fulltext_urls or []
        self.links_download_urls = links_download_urls or []

    @property
    def name(self) -> str:
        return "CORE"

    def can_handle(self, doi: str) -> bool:  # noqa: ARG002
        return True

    def get_pdf_url(self, doi: str) -> str | None:  # noqa: ARG002
        return self.primary_url

    def get_metadata(self, doi: str) -> dict[str, str | int | list[str]]:  # noqa: ARG002
        return {
            "title": "CORE Title",
            "year": 2018,
            "pdf_url": self.primary_url,
            "source_fulltext_urls": self.source_fulltext_urls,
            "links_download_urls": self.links_download_urls,
            "core_download_url": self.primary_url,
        }


class _StubConverter:
    def __init__(self, *, fail: bool = False):
        self.fail = fail

    def convert(
        self, pdf_path: str, md_path: str, *, options: MarkdownConvertOptions
    ) -> tuple[bool, str | None]:
        del options
        if self.fail:
            return False, "conversion failed"
        Path(md_path).write_text(f"converted: {pdf_path}\n", encoding="utf-8")
        return True, None


def test_download_result_includes_metadata_and_progress(tmp_path: Path):
    pdf_url = "https://example.org/paper.pdf"
    session = _FakeSession({pdf_url: _make_fake_pdf_bytes()})
    downloader = FileDownloader(session=session, timeout=5)  # type: ignore[arg-type]

    source_manager = SourceManager(sources=[_StubSource()], enable_year_routing=False)
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,
    )

    progress_events: list[DownloadProgress] = []

    def _callback(progress: DownloadProgress) -> None:
        progress_events.append(progress)

    result = client.download_paper("10.1234/abc", progress_callback=_callback)

    assert result.success
    assert result.file_path
    assert result.source == "Unpaywall"
    assert result.metadata and result.metadata["title"] == "Example Title"
    assert result.title == "Example Title"
    assert result.year == 2020
    assert Path(result.file_path).exists()

    assert progress_events
    assert progress_events[-1].done is True


def test_parallel_download_from_file(tmp_path: Path):
    urls = [
        "https://example.org/a.pdf",
        "https://example.org/b.pdf",
    ]
    session = _FakeSession({url: _make_fake_pdf_bytes() for url in urls})
    downloader = FileDownloader(session=session, timeout=5)  # type: ignore[arg-type]

    sources = [DirectPDFSource()]
    source_manager = SourceManager(sources=sources, enable_year_routing=False)
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,
    )

    input_file = tmp_path / "input.txt"
    input_file.write_text("\n".join(urls), encoding="utf-8")

    results = client.download_from_file(str(input_file), parallel=2)

    assert len(results) == 2
    assert [result.identifier for result in results] == urls
    assert all(result.success for result in results)
    assert all(result.file_path and Path(result.file_path).exists() for result in results)


def test_pdf_to_markdown_postprocess(tmp_path: Path):
    pdf_url = "https://example.org/paper.pdf"
    session = _FakeSession({pdf_url: _make_fake_pdf_bytes()})
    downloader = FileDownloader(session=session, timeout=5)  # type: ignore[arg-type]

    source_manager = SourceManager(sources=[_StubSource()], enable_year_routing=False)
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,
        convert_to_md=True,
        md_output_dir=str(tmp_path / "md"),
        md_converter=_StubConverter(),
    )

    result = client.download_paper("10.1234/abc")

    assert result.success
    assert result.file_path
    assert result.md_success is True
    assert result.md_path
    assert Path(result.md_path).exists()


def test_pdf_to_markdown_failure_sets_fields(tmp_path: Path):
    pdf_url = "https://example.org/paper.pdf"
    session = _FakeSession({pdf_url: _make_fake_pdf_bytes()})
    downloader = FileDownloader(session=session, timeout=5)  # type: ignore[arg-type]

    source_manager = SourceManager(sources=[_StubSource()], enable_year_routing=False)
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,
        convert_to_md=True,
        md_output_dir=str(tmp_path / "md"),
        md_converter=_StubConverter(fail=True),
    )

    result = client.download_paper("10.1234/abc")

    assert result.success
    assert result.file_path
    assert result.md_success is False
    assert result.md_path
    assert result.md_error


def test_core_download_falls_back_to_alternative_metadata_urls(tmp_path: Path):
    primary_url = "https://core.ac.uk/download/primary.pdf"
    fallback_url = "https://repo.example.org/fallback.pdf"
    session = _FakeSession({fallback_url: _make_fake_pdf_bytes()})
    downloader = FileDownloader(session=session, timeout=5)  # type: ignore[arg-type]

    source_manager = SourceManager(
        sources=[
            _CoreFallbackSource(
                primary_url=primary_url,
                source_fulltext_urls=[fallback_url],
            )
        ],
        enable_year_routing=False,
    )
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,
    )

    result = client.download_paper("10.1234/core-fallback")

    assert result.success
    assert result.download_url == fallback_url
    assert result.file_path and Path(result.file_path).exists()


def test_core_download_failure_reports_all_candidate_urls(tmp_path: Path):
    primary_url = "https://core.ac.uk/download/primary.pdf"
    source_fallback_url = "https://repo.example.org/from-source-fulltext.pdf"
    links_fallback_url = "https://repo.example.org/from-links-download.pdf"
    session = _FakeSession({})
    downloader = FileDownloader(session=session, timeout=5)  # type: ignore[arg-type]

    source_manager = SourceManager(
        sources=[
            _CoreFallbackSource(
                primary_url=primary_url,
                source_fulltext_urls=[source_fallback_url],
                links_download_urls=[links_fallback_url],
            )
        ],
        enable_year_routing=False,
    )
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,
    )

    result = client.download_paper("10.1234/core-failure")

    assert not result.success
    assert result.error
    assert "Tried 3 candidate URLs" in result.error
    assert primary_url in result.error
    assert source_fallback_url in result.error
    assert links_fallback_url in result.error
