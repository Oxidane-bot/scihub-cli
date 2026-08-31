from __future__ import annotations

from pathlib import Path

from scihub_cli.client import SciHubClient
from scihub_cli.core.doi_processor import DOIProcessor
from scihub_cli.core.identifier_classifier import select_best_identifier_variant
from scihub_cli.core.source_manager import SourceManager
from scihub_cli.models import DownloadResult


def test_arxiv_url_and_id_forms_share_one_identity_key():
    variants = [
        "https://arxiv.org/abs/1706.03762",
        "https://arxiv.org/pdf/1706.03762.pdf",
        "arxiv:1706.03762",
        "1706.03762",
    ]

    assert {DOIProcessor.normalize_identifier(value) for value in variants} == {"arxiv:1706.03762"}


def test_pmc_hosts_and_bare_pmcid_share_one_identity_key():
    variants = [
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC6505544/",
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6505544/",
        "https://europepmc.org/articles/PMC6505544?pdf=render",
        "PMC6505544",
    ]

    assert {DOIProcessor.normalize_identifier(value) for value in variants} == {"pmc:PMC6505544"}


def test_doi_publisher_variants_share_one_identity_key():
    variants = [
        "10.1000/XYZ",
        "https://doi.org/10.1000/xyz",
        "https://publisher.example/doi/full/10.1000/xyz",
        "https://publisher.example/doi/pdf/10.1000/xyz",
    ]

    assert {DOIProcessor.normalize_identifier(value) for value in variants} == {"10.1000/xyz"}


def test_percent_encoded_publisher_doi_shares_identity_key():
    variants = [
        "10.1000/xyz",
        "https://publisher.example/doi/full/10.1000%2Fxyz",
        "https://publisher.example/doi/pdf/10.1000%2Fxyz.pdf",
    ]

    assert {DOIProcessor.normalize_identifier(value) for value in variants} == {"10.1000/xyz"}
    assert DOIProcessor.normalize_doi(variants[-1]) == "10.1000/xyz"


def test_untrusted_pdf_query_doi_does_not_merge_with_bare_doi():
    untrusted_pdf = "https://downloads.example.invalid/file.pdf?doi=10.1000/xyz"
    bare_doi = "10.1000/xyz"

    assert DOIProcessor.normalize_identifier(untrusted_pdf) != bare_doi
    assert DOIProcessor.normalize_identifier(bare_doi) == bare_doi
    assert select_best_identifier_variant([untrusted_pdf, bare_doi]) == bare_doi


def test_plos_query_doi_remains_a_trusted_doi_variant():
    plos_pdf = (
        "https://journals.plos.org/plosone/article/file?"
        "id=10.1371/journal.pone.0250916&type=printable"
    )

    assert DOIProcessor.normalize_identifier(plos_pdf) == "10.1371/journal.pone.0250916"
    assert select_best_identifier_variant(["10.1371/journal.pone.0250916", plos_pdf]) == plos_pdf


def test_legacy_arxiv_url_and_id_forms_share_one_identity_key():
    variants = [
        "hep-th/9901001",
        "arxiv:hep-th/9901001",
        "https://arxiv.org/abs/hep-th/9901001",
        "https://arxiv.org/pdf/hep-th/9901001.pdf",
    ]

    assert {DOIProcessor.normalize_identifier(value) for value in variants} == {
        "arxiv:hep-th/9901001"
    }


def test_variant_selection_keeps_direct_or_landing_url_over_bare_doi():
    variants = [
        "10.1000/xyz",
        "https://doi.org/10.1000/xyz",
        "https://publisher.example/doi/full/10.1000/xyz",
        "https://publisher.example/doi/pdf/10.1000/xyz.pdf",
    ]

    assert select_best_identifier_variant(variants) == variants[-1]


def test_download_from_file_deduplicates_source_specific_identifier_forms(tmp_path: Path):
    identifiers = [
        "https://arxiv.org/abs/1706.03762",
        "https://arxiv.org/pdf/1706.03762.pdf",
        "arxiv:1706.03762",
        "1706.03762",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC6505544/",
        "https://europepmc.org/articles/PMC6505544?pdf=render",
        "PMC6505544",
    ]
    input_file = tmp_path / "identifiers.txt"
    input_file.write_text("\n".join(identifiers), encoding="utf-8")

    client = SciHubClient(
        output_dir=str(tmp_path / "out"),
        source_manager=SourceManager(sources=[], enable_year_routing=False),
    )
    calls: list[str] = []

    def _fake_download(identifier: str, progress_callback=None):  # noqa: ARG001
        calls.append(identifier)
        return DownloadResult(
            identifier=identifier,
            normalized_identifier=DOIProcessor.normalize_doi(identifier),
            success=True,
        )

    client.download_paper = _fake_download  # type: ignore[method-assign]
    results = client.download_from_file(str(input_file), parallel=2)

    assert len(calls) == 2
    assert "https://arxiv.org/pdf/1706.03762.pdf" in calls
    assert "https://europepmc.org/articles/PMC6505544?pdf=render" in calls
    assert [result.identifier for result in results] == identifiers
