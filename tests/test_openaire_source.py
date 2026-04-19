"""Tests for OpenAireSource."""

from unittest.mock import MagicMock, patch

from scihub_cli.sources.openaire_source import OpenAireSource


def _make_json_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.headers = {"Content-Type": "application/json"}
    return resp


def test_name():
    source = OpenAireSource(timeout=5)
    assert source.name == "OpenAIRE"


def test_can_handle_doi():
    source = OpenAireSource(timeout=5)
    assert source.can_handle("10.1234/test")


def test_cannot_handle_non_doi():
    source = OpenAireSource(timeout=5)
    assert not source.can_handle("arxiv:2301.00001")


def test_get_pdf_url_extracts_link():
    source = OpenAireSource(timeout=5)
    api_data = {
        "response": {
            "results": {
                "result": [
                    {
                        "metadata": {
                            "oaf:entity": {
                                "oaf:result": {
                                    "title": "Test Paper",
                                    "children": {
                                        "instance": [
                                            {
                                                "accessright": {
                                                    "classid": "OPEN",
                                                    "classname": "Open Access",
                                                },
                                                "webresource": [
                                                    {"url": "https://example.com/paper.pdf"}
                                                ],
                                            }
                                        ]
                                    },
                                }
                            }
                        }
                    }
                ]
            }
        }
    }
    mock_response = _make_json_response(api_data)

    with patch.object(source.session, "get", return_value=mock_response):
        url = source.get_pdf_url("10.1234/test")

    assert url == "https://example.com/paper.pdf"


def test_get_pdf_url_no_results():
    source = OpenAireSource(timeout=5)
    api_data = {"response": {"results": {"result": []}}}
    mock_response = _make_json_response(api_data)

    with patch.object(source.session, "get", return_value=mock_response):
        url = source.get_pdf_url("10.1234/nonexistent")

    assert url is None


def test_fast_fail_reduces_timeout():
    source = OpenAireSource(timeout=30, fast_fail=True)
    assert source.timeout <= 5
