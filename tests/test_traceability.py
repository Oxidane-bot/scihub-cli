from __future__ import annotations

from pathlib import Path

from scihub_cli.client import SciHubClient
from scihub_cli.core.downloader import FileDownloader
from scihub_cli.core.source_manager import SourceManager
from scihub_cli.sources.direct_pdf_source import DirectPDFSource
from scihub_cli.sources.html_landing_source import HTMLLandingSource
from scihub_cli.sources.pmc_source import PMCSource


class _FakeResponse:
    def __init__(self, *, status_code: int, text: str, content_type: str = "text/html"):
        self.status_code = status_code
        self.text = text
        self.headers = {"Content-Type": content_type}

    def iter_content(self, chunk_size: int = 8192):  # noqa: ARG002
        return iter(())


class _FakeSession:
    def __init__(self, responses: dict[str, _FakeResponse]):
        self._responses = responses

    def get(self, url: str, timeout=None, stream=False):  # noqa: ARG002
        return self._responses.get(
            url,
            _FakeResponse(status_code=404, text="Not found", content_type="text/html"),
        )


class _NoBypassDownloader(FileDownloader):
    def _download_with_cloudscraper(self, url, output_path, progress_callback=None):  # noqa: ARG002
        return False, "disabled in test"

    def _download_with_curl_cffi(self, url, output_path, progress_callback=None):  # noqa: ARG002
        return False, "disabled in test"


def test_failed_download_contains_source_attempts_and_html_snapshots(tmp_path: Path):
    landing_url = "https://example.org/article/no-pdf"
    html = "<html><head><title>No PDF here</title></head><body>hello</body></html>"

    session = _FakeSession({landing_url: _FakeResponse(status_code=200, text=html)})
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
        trace_html=True,
    )

    result = client.download_paper(landing_url)

    assert not result.success
    assert result.source_attempts

    source_names = [attempt["source"] for attempt in result.source_attempts]
    assert source_names == ["Direct PDF", "PMC", "HTML Landing"]
    assert result.source_attempts[-1]["status"] == "no_result"

    assert result.html_snapshots
    snapshot = result.html_snapshots[0]
    snapshot_path = snapshot["file_path"]
    assert snapshot_path
    assert Path(snapshot_path).exists()
    assert Path(snapshot_path).read_text(encoding="utf-8") == html


def test_failed_file_download_captures_download_phase_html(tmp_path: Path):
    pdf_url = "https://example.org/not-a-real.pdf"
    html = "<html><body>blocked by portal</body></html>"
    session = _FakeSession({pdf_url: _FakeResponse(status_code=200, text=html)})
    downloader = _NoBypassDownloader(session=session, timeout=5)  # type: ignore[arg-type]

    source_manager = SourceManager(sources=[DirectPDFSource()], enable_year_routing=False)
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,
        source_manager=source_manager,
        trace_html=True,
    )

    result = client.download_paper(pdf_url)

    assert not result.success
    assert result.html_snapshots

    download_snapshot = next(
        (
            snapshot
            for snapshot in result.html_snapshots
            if snapshot.get("phase") == "download" and snapshot.get("fetcher") == "requests"
        ),
        None,
    )
    assert download_snapshot is not None
    assert download_snapshot["file_path"]
    snapshot_path = Path(str(download_snapshot["file_path"]))
    assert snapshot_path.exists()
    assert "blocked by portal" in snapshot_path.read_text(encoding="utf-8")
