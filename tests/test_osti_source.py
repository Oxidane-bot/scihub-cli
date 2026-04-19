"""Tests for OSTISource."""

from scihub_cli.sources.osti_source import OSTISource


def test_can_handle_osti_doi():
    source = OSTISource()
    assert source.can_handle("10.2172/1234567")


def test_can_handle_osti_doi_with_prefix():
    source = OSTISource()
    assert source.can_handle("https://doi.org/10.2172/1234567")


def test_cannot_handle_non_osti_doi():
    source = OSTISource()
    assert not source.can_handle("10.1038/nature12373")


def test_cannot_handle_empty():
    source = OSTISource()
    assert not source.can_handle("")


def test_get_pdf_url_returns_osti_endpoint():
    source = OSTISource()
    url = source.get_pdf_url("10.2172/1234567")
    assert url == "https://www.osti.gov/servlets/purl/1234567"


def test_get_pdf_url_extracts_from_full_url():
    source = OSTISource()
    url = source.get_pdf_url("https://doi.org/10.2172/9999")
    assert url == "https://www.osti.gov/servlets/purl/9999"


def test_get_pdf_url_returns_none_for_non_osti():
    source = OSTISource()
    assert source.get_pdf_url("10.1038/nature12373") is None


def test_name():
    source = OSTISource()
    assert source.name == "OSTI"
