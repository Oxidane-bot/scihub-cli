"""Tests for SemanticScholarSource."""

from unittest.mock import MagicMock, patch

from scihub_cli.sources.semantic_scholar_source import SemanticScholarSource


def _make_json_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.headers = {"Content-Type": "application/json"}
    return resp


def test_name():
    source = SemanticScholarSource(timeout=5)
    assert source.name == "Semantic Scholar"


def test_can_handle_doi():
    source = SemanticScholarSource(timeout=5)
    assert source.can_handle("10.1038/nature12373")


def test_cannot_handle_non_doi():
    source = SemanticScholarSource(timeout=5)
    assert not source.can_handle("https://example.com/paper")


def test_get_pdf_url_with_oa_url():
    source = SemanticScholarSource(timeout=5)
    mock_response = _make_json_response({
        "openAccessPdf": {"url": "https://example.com/paper.pdf"},
    })

    with patch.object(source.session, "get", return_value=mock_response):
        url = source.get_pdf_url("10.1038/nature12373")

    assert url == "https://example.com/paper.pdf"


def test_get_pdf_url_no_oa_pdf():
    source = SemanticScholarSource(timeout=5)
    mock_response = _make_json_response({
        "openAccessPdf": None,
    })

    with patch.object(source.session, "get", return_value=mock_response):
        url = source.get_pdf_url("10.1038/nature12373")

    assert url is None


def test_get_pdf_url_api_404():
    source = SemanticScholarSource(timeout=5)
    mock_response = _make_json_response({"error": "Not found"}, status_code=404)

    with patch.object(source.session, "get", return_value=mock_response):
        url = source.get_pdf_url("10.1038/nonexistent")

    assert url is None


def test_fast_fail_reduces_timeout():
    source = SemanticScholarSource(timeout=30, fast_fail=True)
    assert source.timeout <= 5
