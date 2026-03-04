from __future__ import annotations

from dataclasses import dataclass

from scihub_cli.sources.openalex_source import OpenAlexSource


@dataclass
class _StubResponse:
    status_code: int
    payload: dict

    def json(self):
        return self.payload


class _StubSession:
    def __init__(self, response: _StubResponse):
        self._response = response

    def get(self, url: str, params=None, timeout=None):  # noqa: ARG002
        return self._response


def test_openalex_can_handle_doi_only():
    source = OpenAlexSource(timeout=5)
    assert source.can_handle("10.1038/nature12373")
    assert not source.can_handle("https://example.org/article")


def test_openalex_get_pdf_url_from_best_oa_location():
    source = OpenAlexSource(timeout=5, email="test@example.com")
    source.session = _StubSession(
        _StubResponse(
            status_code=200,
            payload={
                "results": [
                    {
                        "id": "https://openalex.org/W123",
                        "title": "Example",
                        "publication_year": 2024,
                        "open_access": {
                            "is_oa": True,
                            "oa_status": "gold",
                            "oa_url": "https://example.org/landing",
                        },
                        "best_oa_location": {
                            "pdf_url": "https://example.org/paper.pdf",
                            "landing_page_url": "https://example.org/landing",
                        },
                        "primary_location": {"source": {"display_name": "Example Journal"}},
                        "locations": [],
                    }
                ]
            },
        )
    )

    url = source.get_pdf_url("10.1000/xyz")
    metadata = source.get_metadata("10.1000/xyz")

    assert url == "https://example.org/paper.pdf"
    assert metadata is not None
    assert metadata["year"] == 2024
    assert metadata["journal"] == "Example Journal"
    assert metadata["is_oa"] is True


def test_openalex_falls_back_to_open_access_oa_url_pdf():
    source = OpenAlexSource(timeout=5)
    source.session = _StubSession(
        _StubResponse(
            status_code=200,
            payload={
                "results": [
                    {
                        "id": "https://openalex.org/W124",
                        "title": "Fallback OA URL",
                        "publication_year": 2019,
                        "open_access": {
                            "is_oa": True,
                            "oa_status": "green",
                            "oa_url": "https://repo.org/download/paper.pdf",
                        },
                        "best_oa_location": {"pdf_url": None, "landing_page_url": None},
                        "primary_location": {"source": {"display_name": "Repo"}},
                        "locations": [],
                    }
                ]
            },
        )
    )

    assert source.get_pdf_url("10.2000/abc") == "https://repo.org/download/paper.pdf"


def test_openalex_returns_none_for_non_oa_work():
    source = OpenAlexSource(timeout=5)
    source.session = _StubSession(
        _StubResponse(
            status_code=200,
            payload={
                "results": [
                    {
                        "id": "https://openalex.org/W125",
                        "title": "Closed",
                        "publication_year": 2018,
                        "open_access": {"is_oa": False, "oa_status": "closed"},
                        "best_oa_location": {},
                        "primary_location": {"source": {"display_name": "Closed Journal"}},
                        "locations": [],
                    }
                ]
            },
        )
    )

    assert source.get_pdf_url("10.3000/closed") is None


def test_openalex_fast_fail_uses_short_timeout_and_single_attempt():
    source = OpenAlexSource(timeout=12, fast_fail=True)
    assert source.timeout == 5
    assert source.retry_config.max_attempts == 2
