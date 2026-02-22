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
    def __init__(
        self, content: bytes, status_code: int = 200, content_type: str = "application/pdf"
    ):
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


class _FailIfFetchedDownloader:
    def get_page_content(self, url: str):  # noqa: ARG002
        raise AssertionError("Should not fetch non-academic URL in fail-fast path")


class _ProbeAwareDownloader(_StubDownloader):
    def __init__(self, html: str, probe_ok: set[str]):
        super().__init__(html=html, status=200)
        self._probe_ok = probe_ok

    def probe_pdf_url(self, url: str) -> bool:
        return url in self._probe_ok


class _FastFailNoFetchDownloader:
    fast_fail = True

    def get_page_content(self, url: str):  # noqa: ARG002
        raise AssertionError("Should not fetch page in this fast-fail scenario")

    def probe_pdf_url(self, url: str) -> bool:  # noqa: ARG002
        return False


class _FastFailNoProbeNoFetchDownloader:
    fast_fail = True

    def get_page_content(self, url: str):  # noqa: ARG002
        raise AssertionError("Should not fetch page for challenge-heavy host in fast-fail mode")

    def probe_pdf_url(self, url: str) -> bool:  # noqa: ARG002
        raise AssertionError("Should not probe derived candidates for challenge-heavy host")


class _FastFailMdpiForceBypassDownloader:
    fast_fail = True

    def __init__(self):
        self.force_bypass_calls = 0

    def probe_pdf_url(self, url: str) -> bool:  # noqa: ARG002
        return False

    def get_page_content(self, url: str, **kwargs):  # noqa: ARG002
        if kwargs.get("force_challenge_bypass"):
            self.force_bypass_calls += 1
        return "<html></html>", 403


class _FastFailDerivedCandidateDownloader:
    fast_fail = True

    def __init__(self, probe_ok: set[str]):
        self._probe_ok = probe_ok

    def get_page_content(self, url: str):  # noqa: ARG002
        raise AssertionError("Should not fetch page when derived candidate probes successfully")

    def probe_pdf_url(self, url: str) -> bool:
        return url in self._probe_ok


class _FastFailRejectUnprobedDownloader:
    fast_fail = True

    def __init__(self, html: str):
        self._html = html

    def get_page_content(self, url: str):  # noqa: ARG002
        return self._html, 200

    def probe_pdf_url(self, url: str) -> bool:  # noqa: ARG002
        return False


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
    assert result.success, "Expected download to succeed for HTML landing page URL"
    assert result.file_path
    assert Path(result.file_path).exists()
    assert Path(result.file_path).read_bytes()[:4] == b"%PDF"


def test_html_landing_skips_obvious_non_academic_host():
    source = HTMLLandingSource(downloader=_FailIfFetchedDownloader())  # type: ignore[arg-type]
    assert source.get_pdf_url("https://tiktok.com/discover/jaguar-brand-manager") is None


def test_html_landing_skips_news_like_non_academic_host():
    source = HTMLLandingSource(downloader=_FailIfFetchedDownloader())  # type: ignore[arg-type]
    assert (
        source.get_pdf_url(
            "https://consumerreports.org/media-room/press-releases/2026/02/new-cars/"
        )
        is None
    )


def test_html_landing_keeps_likely_academic_edu_host():
    source = HTMLLandingSource(downloader=_StubDownloader(html="<html></html>"))  # type: ignore[arg-type]
    assert source.can_handle("https://minds.wisconsin.edu/handle/1793/7889")


def test_html_landing_uses_probe_to_pick_valid_candidate():
    html = """
    <html><body>
      <a href="/download/challenge">Download</a>
      <a href="/content/paper.pdf">Download PDF</a>
    </body></html>
    """
    base_url = "https://example.org/article/123"
    expected = "https://example.org/content/paper.pdf"
    source = HTMLLandingSource(downloader=_ProbeAwareDownloader(html=html, probe_ok={expected}))  # type: ignore[arg-type]

    assert source.get_pdf_url(base_url) == expected


def test_html_landing_fast_fail_skips_unknown_news_host():
    source = HTMLLandingSource(downloader=_FastFailNoFetchDownloader())  # type: ignore[arg-type]
    assert source.get_pdf_url("https://thetrailblazer.co.uk/news/jaguar-rebrand") is None


def test_html_landing_prefers_derived_publisher_candidate_without_fetch():
    base_url = "https://www.nature.com/articles/s41598-024-75283-7"
    derived = "https://www.nature.com/articles/s41598-024-75283-7.pdf"
    source = HTMLLandingSource(downloader=_FastFailDerivedCandidateDownloader(probe_ok={derived}))  # type: ignore[arg-type]
    assert source.get_pdf_url(base_url) == derived


def test_html_landing_fast_fail_skips_html_fetch_for_sciencedirect_when_probe_fails():
    source = HTMLLandingSource(downloader=_FastFailNoFetchDownloader())  # type: ignore[arg-type]
    assert (
        source.get_pdf_url(
            "https://www.sciencedirect.com/science/article/abs/pii/S1364032121006948"
        )
        is None
    )


def test_html_landing_fast_fail_skips_sciencedirect_before_prefetch_probe():
    source = HTMLLandingSource(downloader=_FastFailNoProbeNoFetchDownloader())  # type: ignore[arg-type]
    assert (
        source.get_pdf_url(
            "https://www.sciencedirect.com/science/article/abs/pii/S0306261917303884"
        )
        is None
    )


def test_html_landing_fast_fail_forces_page_bypass_for_mdpi():
    downloader = _FastFailMdpiForceBypassDownloader()
    source = HTMLLandingSource(downloader=downloader)  # type: ignore[arg-type]

    assert source.get_pdf_url("https://www.mdpi.com/") is None
    assert downloader.force_bypass_calls == 1


def test_html_landing_fast_fail_rejects_unprobed_candidates():
    html = """
    <html><body>
      <a href="/download/challenge">Download PDF</a>
      <a href="/article/download">PDF</a>
    </body></html>
    """
    source = HTMLLandingSource(downloader=_FastFailRejectUnprobedDownloader(html=html))  # type: ignore[arg-type]

    assert source.get_pdf_url("https://academia.edu/12345/example") is None
