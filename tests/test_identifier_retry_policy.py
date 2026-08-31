from pathlib import Path
from typing import Any

import pytest

from scihub_cli.client import SciHubClient
from scihub_cli.core.identifier_classifier import (
    is_retryable_identifier,
    select_retry_identifier,
    should_retry_sources_after_download_failure,
)


@pytest.mark.parametrize("message", ["HTTP 408", "HTTP 425", "HTTP 429"])
def test_transient_http_statuses_trigger_source_fallback(message: str):
    assert should_retry_sources_after_download_failure(message)


@pytest.mark.parametrize("status", [400, 401, 404, 409, 418, 422, 451])
def test_permanent_http_statuses_do_not_trigger_source_fallback(status: int):
    assert not should_retry_sources_after_download_failure(f"HTTP {status}")


def test_forbidden_http_status_remains_an_alternate_provider_signal():
    assert should_retry_sources_after_download_failure("HTTP 403")


def test_strong_pmc_identifier_cannot_be_replaced_by_page_doi():
    pmc_url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC7153055"
    page_doi = "10.1136/amiajnl-2013-002428"

    assert select_retry_identifier(pmc_url, {"doi": page_doi}) == pmc_url
    assert is_retryable_identifier(pmc_url)


def test_explicit_doi_cannot_be_replaced_by_page_doi():
    requested_doi = "10.1234/requested-paper"
    page_doi = "10.5678/unrelated-paper"

    assert select_retry_identifier(requested_doi, {"doi": page_doi}) == requested_doi


def test_weak_landing_url_still_uses_metadata_doi_fallback():
    landing_url = "https://repository.example/item/7153055"
    metadata_doi = "10.1234/repository-paper"

    assert select_retry_identifier(landing_url, {"doi": metadata_doi}) == metadata_doi


class _PmcIdentitySourceManager:
    def __init__(self, first_url: str, fallback_url: str, wrong_doi: str):
        self.first_url = first_url
        self.fallback_url = fallback_url
        self.wrong_doi = wrong_doi
        self.calls: list[dict[str, Any]] = []

    def get_pdf_url_with_metadata_and_trace(
        self,
        identifier: str,
        *,
        exclude_sources: set[str] | None = None,
        force_sequential: bool = False,
        html_snapshot_callback=None,
    ):
        self.calls.append(
            {
                "identifier": identifier,
                "exclude_sources": set(exclude_sources or ()),
                "force_sequential": force_sequential,
            }
        )
        if len(self.calls) == 1:
            return (
                self.first_url,
                {"title": "PMC paper", "year": 2020, "doi": self.wrong_doi},
                "PMC",
                [{"source": "PMC", "status": "success", "pdf_url": self.first_url}],
            )
        return (
            self.fallback_url,
            {"title": "PMC paper", "year": 2020},
            "Unpaywall",
            [{"source": "Unpaywall", "status": "success", "pdf_url": self.fallback_url}],
        )


class _FailPmcThenSucceedDownloader:
    def __init__(self, failing_url: str, success_url: str):
        self.failing_url = failing_url
        self.success_url = success_url
        self.calls: list[str] = []

    def download_file(self, url: str, output_path: str, progress_callback=None):
        self.calls.append(url)
        if url == self.failing_url:
            return False, "HTTP 503"
        if url == self.success_url:
            Path(output_path).write_bytes(b"%PDF-1.4\n" + b"0" * 12000 + b"\n%%EOF\n")
            return True, None
        return False, "unexpected URL"


def test_pmc_retry_queries_same_pmcid_instead_of_scraped_doi(tmp_path: Path):
    pmc_url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC7153055"
    wrong_doi = "10.1136/amiajnl-2013-002428"
    first_url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC7153055/pdf/"
    fallback_url = "https://repository.example/PMC7153055.pdf"
    source_manager = _PmcIdentitySourceManager(first_url, fallback_url, wrong_doi)
    downloader = _FailPmcThenSucceedDownloader(first_url, fallback_url)
    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        timeout=5,
        retries=1,
        downloader=downloader,  # type: ignore[arg-type]
        source_manager=source_manager,  # type: ignore[arg-type]
    )

    result = client.download_paper(pmc_url)

    assert result.success
    assert downloader.calls[0] == first_url
    assert downloader.calls[-1] == fallback_url
    assert len(downloader.calls) == 4
    assert len(source_manager.calls) == 2
    retry_call = source_manager.calls[1]
    assert retry_call["identifier"] == pmc_url
    assert retry_call["identifier"] != wrong_doi
    assert retry_call["exclude_sources"] == {"PMC"}
