from __future__ import annotations

from pathlib import Path
from typing import Any

from scihub_cli.client import SciHubClient


def _make_fake_pdf_bytes(size: int = 12000) -> bytes:
    header = b"%PDF-1.4\n"
    trailer = b"\n%%EOF\n"
    return header + b"0" * (size - len(header) - len(trailer)) + trailer


class _RequeryingSourceManager:
    def __init__(self, first_url: str, fallback_url: str):
        self.first_url = first_url
        self.fallback_url = fallback_url
        self.calls: list[dict[str, Any]] = []

    def get_pdf_url_with_metadata_and_trace(
        self,
        identifier: str,
        year: int | None = None,  # noqa: ARG002
        html_snapshot_callback=None,  # noqa: ARG002
        *,
        exclude_sources: set[str] | None = None,
        force_sequential: bool = False,
    ) -> tuple[str, dict[str, Any], str, list[dict[str, Any]]]:
        excluded = set(exclude_sources or ())
        self.calls.append(
            {
                "identifier": identifier,
                "exclude_sources": excluded,
                "force_sequential": force_sequential,
            }
        )
        if "OpenAlex" in excluded:
            return (
                self.fallback_url,
                {"title": "Fallback paper", "year": 2020, "doi": identifier},
                "Unpaywall",
                [
                    {
                        "source": "Unpaywall",
                        "status": "success",
                        "pdf_url": self.fallback_url,
                    }
                ],
            )
        return (
            self.first_url,
            {"title": "Fallback paper", "year": 2020, "doi": identifier},
            "OpenAlex",
            [
                {
                    "source": "OpenAlex",
                    "status": "success",
                    "pdf_url": self.first_url,
                }
            ],
        )


class _FailThenSucceedDownloader:
    def __init__(self, failing_url: str, success_url: str, *, invalid_first: bool = False):
        self.failing_url = failing_url
        self.success_url = success_url
        self.invalid_first = invalid_first
        self.calls: list[str] = []

    def download_file(self, url: str, output_path: str, progress_callback=None):  # noqa: ARG002
        self.calls.append(url)
        if url == self.failing_url:
            if self.invalid_first:
                Path(output_path).write_bytes(b"not a pdf")
                return True, None
            return False, "HTTP 503"
        Path(output_path).write_bytes(_make_fake_pdf_bytes())
        return True, None


class _FailSeveralThenSucceedDownloader:
    def __init__(
        self,
        failing_urls: set[str],
        success_url: str | None,
        failure_messages: dict[str, str] | None = None,
    ):
        self.failing_urls = failing_urls
        self.success_url = success_url
        self.failure_messages = failure_messages or {}
        self.calls: list[str] = []

    def download_file(self, url: str, output_path: str, progress_callback=None):  # noqa: ARG002
        self.calls.append(url)
        if url in self.failing_urls:
            return False, self.failure_messages.get(url, "HTTP 503")
        if self.success_url and url == self.success_url:
            Path(output_path).write_bytes(_make_fake_pdf_bytes())
            return True, None
        return False, "unexpected URL"


class _RepeatingCandidateSourceManager:
    def __init__(self, first_urls: list[str], retry_urls: list[str]):
        self.first_urls = first_urls
        self.retry_urls = retry_urls
        self.calls: list[dict[str, Any]] = []

    def get_pdf_url_with_metadata_and_trace(
        self,
        identifier: str,
        year: int | None = None,  # noqa: ARG002
        html_snapshot_callback=None,  # noqa: ARG002
        *,
        exclude_sources: set[str] | None = None,
        force_sequential: bool = False,
    ) -> tuple[str, dict[str, Any], str, list[dict[str, Any]]]:
        excluded = set(exclude_sources or ())
        self.calls.append(
            {
                "identifier": identifier,
                "exclude_sources": excluded,
                "force_sequential": force_sequential,
            }
        )
        urls = self.first_urls if len(self.calls) == 1 else self.retry_urls
        attempts = [{"source": "OpenAlex", "status": "success", "pdf_url": url} for url in urls]
        return urls[0], {"title": "Repeated candidates", "doi": identifier}, "OpenAlex", attempts


def _make_client(
    tmp_path: Path,
    source_manager: _RequeryingSourceManager,
    downloader: _FailThenSucceedDownloader,
) -> SciHubClient:
    return SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,  # type: ignore[arg-type]
        source_manager=source_manager,  # type: ignore[arg-type]
    )


def test_transient_primary_download_failure_requeries_another_source(tmp_path: Path):
    first_url = "https://openalex.example/paper.pdf"
    fallback_url = "https://unpaywall.example/paper.pdf"
    source_manager = _RequeryingSourceManager(first_url, fallback_url)
    downloader = _FailThenSucceedDownloader(first_url, fallback_url)
    client = _make_client(tmp_path, source_manager, downloader)

    result = client.download_paper("10.1234/fallback")

    assert result.success
    assert result.source == "Unpaywall"
    assert result.download_url == fallback_url
    assert downloader.calls == [first_url, fallback_url]
    assert len(source_manager.calls) == 2
    assert source_manager.calls[1]["exclude_sources"] == {"OpenAlex"}
    assert source_manager.calls[1]["force_sequential"] is True
    assert any(
        attempt.get("phase") == "source_fallback" and attempt.get("status") == "retrying"
        for attempt in result.source_attempts or []
    )


def test_validation_failure_requeries_another_source(tmp_path: Path):
    first_url = "https://openalex.example/invalid.pdf"
    fallback_url = "https://unpaywall.example/valid.pdf"
    source_manager = _RequeryingSourceManager(first_url, fallback_url)
    downloader = _FailThenSucceedDownloader(first_url, fallback_url, invalid_first=True)
    client = _make_client(tmp_path, source_manager, downloader)

    result = client.download_paper("10.1234/invalid-fallback")

    assert result.success
    assert result.source == "Unpaywall"
    assert downloader.calls == [first_url, fallback_url]
    assert len(source_manager.calls) == 2


def test_source_fallback_is_bounded_when_manager_repeats_source(tmp_path: Path):
    first_url = "https://openalex.example/repeated.pdf"
    source_manager = _RequeryingSourceManager(first_url, first_url)
    downloader = _FailThenSucceedDownloader(first_url, first_url)
    client = _make_client(tmp_path, source_manager, downloader)

    result = client.download_paper("10.1234/repeated")

    assert not result.success
    # The repeated provider is queried once for a fallback, but its already
    # tried URL is filtered before another download attempt.
    assert len(source_manager.calls) == 2
    assert len(downloader.calls) == 1
    assert any(
        attempt.get("reason") == "all_candidates_already_tried"
        for attempt in result.source_attempts or []
    )


def test_fallback_filters_repeated_urls_but_keeps_new_candidate(tmp_path: Path):
    url_a = "https://openalex.example/a.pdf"
    url_b = "https://openalex.example/b.pdf"
    url_c = "https://openalex.example/c.pdf"
    source_manager = _RepeatingCandidateSourceManager([url_a, url_b], [url_a, url_c])
    downloader = _FailSeveralThenSucceedDownloader({url_a, url_b}, url_c)
    client = _make_client(tmp_path, source_manager, downloader)

    result = client.download_paper("10.1234/repeated-candidates")

    assert result.success
    assert downloader.calls == [url_a, url_b, url_c]
    assert len(set(downloader.calls)) == len(downloader.calls)
    assert len(source_manager.calls) == 2
    retry_trace = [
        attempt
        for attempt in result.source_attempts or []
        if attempt.get("phase") == "source_fallback" and attempt.get("status") == "retrying"
    ]
    assert len(retry_trace) == 1
    assert retry_trace[0]["failed_candidates"] == [
        {"url": url_a, "error": "HTTP 503"},
        {"url": url_b, "error": "HTTP 503"},
    ]


def test_fallback_decision_uses_only_current_round_errors(tmp_path: Path):
    url_a = "https://openalex.example/old-transient.pdf"
    url_c = "https://openalex.example/current-permanent.pdf"
    source_manager = _RepeatingCandidateSourceManager([url_a], [url_a, url_c])
    downloader = _FailSeveralThenSucceedDownloader(
        {url_a, url_c},
        None,
        failure_messages={url_a: "HTTP 503", url_c: "permanent failure"},
    )
    client = _make_client(tmp_path, source_manager, downloader)

    result = client.download_paper("10.1234/current-round-errors")

    assert not result.success
    assert downloader.calls == [url_a, url_c]
    # The old transient error must not trigger another source lookup after
    # the current round reports a non-retryable failure.
    assert len(source_manager.calls) == 2
    assert (
        sum(
            attempt.get("status") == "retrying"
            for attempt in result.source_attempts or []
            if attempt.get("phase") == "source_fallback"
        )
        == 1
    )
