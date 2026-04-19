from __future__ import annotations

from pathlib import Path
from typing import Any

from scihub_cli.client import SciHubClient
from scihub_cli.converters.pdf_to_md import MarkdownConvertOptions
from scihub_cli.core.downloader import FileDownloader
from scihub_cli.core.source_manager import SourceManager
from scihub_cli.models import DownloadProgress, DownloadResult
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


class _PMCFallbackSource(PaperSource):
    def __init__(self, *, primary_url: str):
        self.primary_url = primary_url

    @property
    def name(self) -> str:
        return "PMC"

    def can_handle(self, doi: str) -> bool:  # noqa: ARG002
        return True

    def get_pdf_url(self, doi: str) -> str | None:  # noqa: ARG002
        return self.primary_url


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


class _RecordingSourceManager:
    def __init__(self, responses: dict[str, tuple[str | None, dict[str, Any] | None, str | None]]):
        self._responses = responses
        self.calls: list[str] = []

    def get_pdf_url_with_metadata_and_trace(
        self,
        identifier: str,
        year: int | None = None,  # noqa: ARG002
        html_snapshot_callback=None,  # noqa: ARG002
        *,
        exclude_sources: set[str] | None = None,  # noqa: ARG002
        force_sequential: bool = False,  # noqa: ARG002
    ) -> tuple[str | None, dict[str, Any] | None, str | None, list[dict[str, Any]]]:
        self.calls.append(identifier)
        pdf_url, metadata, source = self._responses.get(identifier, (None, None, None))
        status = "success" if pdf_url else "no_result"
        return pdf_url, metadata, source, [{"source": source or "stub", "status": status}]


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


def test_download_from_file_academic_only_filters_non_academic_urls(tmp_path: Path):
    identifiers = [
        "https://tiktok.com/discover/jaguar-brand-manager",
        "https://news.sky.com/story/jaguar-boss-says-we-want-to-be-bold-and-disruptive-13265700",
        "10.1016/j.rser.2021.111658",
        "https://minds.wisconsin.edu/handle/1793/7889",
    ]
    input_file = tmp_path / "input-academic-only.txt"
    input_file.write_text("\n".join(identifiers), encoding="utf-8")

    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        source_manager=SourceManager(sources=[DirectPDFSource()], enable_year_routing=False),
        academic_only=True,
    )
    calls: list[str] = []

    def _fake_download(identifier: str, progress_callback=None):  # noqa: ARG001
        calls.append(identifier)
        return DownloadResult(
            identifier=identifier,
            normalized_identifier=identifier,
            success=False,
            error="stub",
        )

    client.download_paper = _fake_download  # type: ignore[method-assign]
    results = client.download_from_file(str(input_file), parallel=1)

    assert calls == [
        "10.1016/j.rser.2021.111658",
        "https://minds.wisconsin.edu/handle/1793/7889",
    ]
    assert [result.identifier for result in results] == calls


def test_academic_only_filter_drops_unknown_commercial_urls(tmp_path: Path):
    identifiers = [
        "https://bruceturkel.com/branding-and-digital-marketing",
        "https://themodems.com/jaguar-rebrand-case-study",
        "https://autoweek.com/news/industry-news/a1234567/jaguar-rebrand",
        "https://doi.org/10.1016/j.rser.2021.111658",
        "https://journal.example.net/article/1234",
    ]
    input_file = tmp_path / "input-academic-strict.txt"
    input_file.write_text("\n".join(identifiers), encoding="utf-8")

    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        source_manager=SourceManager(sources=[DirectPDFSource()], enable_year_routing=False),
        academic_only=True,
    )
    calls: list[str] = []

    def _fake_download(identifier: str, progress_callback=None):  # noqa: ARG001
        calls.append(identifier)
        return DownloadResult(
            identifier=identifier,
            normalized_identifier=identifier,
            success=False,
            error="stub",
        )

    client.download_paper = _fake_download  # type: ignore[method-assign]
    client.download_from_file(str(input_file), parallel=1)

    assert calls == [
        "https://doi.org/10.1016/j.rser.2021.111658",
        "https://journal.example.net/article/1234",
    ]


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


def test_pmc_download_falls_back_to_europepmc_when_primary_returns_html(tmp_path: Path):
    pmc_id = "PMC1234567"
    primary_url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/pdf/main.pdf"
    backend_url = f"https://europepmc.org/backend/ptpmcrender.fcgi?accid={pmc_id}&blobtype=pdf"
    fallback_url = f"https://europepmc.org/articles/{pmc_id}?pdf=render"

    session = _FakeSession(
        {
            primary_url: b"<html>Preparing to download ...</html>",
            backend_url: _make_fake_pdf_bytes(),
            fallback_url: _make_fake_pdf_bytes(),
        }
    )
    downloader = FileDownloader(session=session, timeout=5, fast_fail=True, retries=1)  # type: ignore[arg-type]

    source_manager = SourceManager(
        sources=[_PMCFallbackSource(primary_url=primary_url)],
        enable_year_routing=False,
    )
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,
        fast_fail=True,
    )

    result = client.download_paper(f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/")

    assert result.success
    assert result.download_url in {backend_url, fallback_url}
    assert result.file_path and Path(result.file_path).exists()


def test_collect_download_candidates_adds_europepmc_for_named_pmc_pdf(tmp_path: Path):
    primary_url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC7654321/pdf/entropy-25-00882.pdf"
    backend_url = "https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC7654321&blobtype=pdf"
    fallback_url = "https://europepmc.org/articles/PMC7654321?pdf=render"
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        source_manager=SourceManager(sources=[DirectPDFSource()], enable_year_routing=False),
    )

    candidates = client._collect_download_candidates(
        primary_url=primary_url,
        source="PMC",
        metadata=None,
    )

    assert candidates == [primary_url, backend_url, fallback_url]


def test_collect_download_candidates_normalizes_markdown_concatenated_urls(tmp_path: Path):
    primary_url = "https://example.org/article"
    polluted = "https://cdn.example.org/paper.pdf)](https://www.mdpi.com/books)"
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        source_manager=SourceManager(sources=[DirectPDFSource()], enable_year_routing=False),
    )

    candidates = client._collect_download_candidates(
        primary_url=primary_url,
        source="CORE",
        metadata={"pdf_url": polluted},
    )

    assert "https://cdn.example.org/paper.pdf" in candidates
    assert all(")](" not in url for url in candidates)


def test_url_input_tries_url_specific_sources_before_doi_fallback(tmp_path: Path):
    landing_url = "https://doi.org/10.1111/rmir.12114"
    normalized_doi = "10.1111/rmir.12114"
    pdf_url = "https://example.org/rmir-12114.pdf"
    session = _FakeSession({pdf_url: _make_fake_pdf_bytes()})
    downloader = FileDownloader(session=session, timeout=5)  # type: ignore[arg-type]

    source_manager = _RecordingSourceManager(
        {
            landing_url: (None, None, None),
            normalized_doi: (
                pdf_url,
                {"title": "RMIR Article", "year": 2024, "doi": normalized_doi},
                "OpenAlex",
            ),
        }
    )
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,  # type: ignore[arg-type]
    )

    result = client.download_paper(landing_url)

    assert result.success
    assert result.file_path
    assert result.normalized_identifier == normalized_doi
    assert source_manager.calls == [landing_url, normalized_doi]


def test_extract_identifier_from_line_preserves_plain_doi_url():
    landing_url = "https://doi.org/10.1111/rmir.12114"

    from scihub_cli.core.identifier_classifier import extract_identifier_from_line

    extracted = extract_identifier_from_line(landing_url)

    assert extracted == landing_url


def test_url_input_short_circuits_when_url_specific_lookup_succeeds(tmp_path: Path):
    landing_url = "https://academic.oup.com/ijlct/article/16/4/1135/6263493"
    pdf_url = "https://academic.oup.com/ijlct/article-pdf/16/4/1135/6263493.pdf"
    session = _FakeSession({pdf_url: _make_fake_pdf_bytes()})
    downloader = FileDownloader(session=session, timeout=5)  # type: ignore[arg-type]

    source_manager = _RecordingSourceManager(
        {
            landing_url: (
                pdf_url,
                {"title": "OUP Article", "year": 2021},
                "HTML Landing",
            ),
        }
    )
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,  # type: ignore[arg-type]
    )

    result = client.download_paper(landing_url)

    assert result.success
    assert result.source == "HTML Landing"
    assert source_manager.calls == [landing_url]


def test_sciencedirect_url_can_fallback_to_resolved_doi_after_url_lookup(tmp_path: Path):
    article_url = "https://sciencedirect.com/science/article/abs/pii/S036054429600165X"
    resolved_doi = "10.1016/s0360-5442(96)00165-x"
    pdf_url = "https://example.org/s036054429600165x.pdf"
    session = _FakeSession({pdf_url: _make_fake_pdf_bytes()})
    downloader = FileDownloader(session=session, timeout=5)  # type: ignore[arg-type]

    source_manager = _RecordingSourceManager(
        {
            article_url: (None, None, None),
            resolved_doi: (
                pdf_url,
                {"title": "ScienceDirect Article", "year": 1996, "doi": resolved_doi},
                "Sci-Hub",
            ),
        }
    )
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,  # type: ignore[arg-type]
    )

    client._resolve_sciencedirect_pii_to_doi = lambda identifier: resolved_doi  # type: ignore[method-assign]

    result = client.download_paper(article_url)

    assert result.success
    assert result.file_path
    assert result.normalized_identifier == resolved_doi
    assert source_manager.calls == [article_url, resolved_doi]
