from __future__ import annotations

from dataclasses import dataclass

from scihub_cli.sources.core_source import CORESource


@dataclass
class _StubResponse:
    status_code: int
    content_type: str
    body: bytes = b""

    @property
    def headers(self) -> dict[str, str]:
        return {"Content-Type": self.content_type}

    def iter_content(self, chunk_size: int = 4):
        for i in range(0, len(self.body), chunk_size):
            yield self.body[i : i + chunk_size]

    def close(self):
        return None


class _StubSession:
    def __init__(self, responses: dict[str, _StubResponse]):
        self.responses = responses

    def get(self, url: str, timeout=None, stream=False, allow_redirects=True):  # noqa: ARG002
        return self.responses[url]


def test_core_selects_source_fulltext_pdf_over_core_proxy():
    source = CORESource(api_key=None, timeout=5)
    source.session = _StubSession(
        {
            "https://lume.ufrgs.br/bitstream/10183/259834/1/001168979.pdf": _StubResponse(
                status_code=200,
                content_type="application/pdf",
                body=b"%PDF-1.4",
            ),
            "http://dx.doi.org/10.1371/journal.pone.0276202": _StubResponse(
                status_code=200,
                content_type="text/html",
                body=b"<!DOCTYPE html>",
            ),
            "https://core.ac.uk/download/576869773.pdf": _StubResponse(
                status_code=403,
                content_type="text/html",
                body=b"",
            ),
        }
    )
    work = {
        "downloadUrl": "https://core.ac.uk/download/576869773.pdf",
        "sourceFulltextUrls": [
            "https://lume.ufrgs.br/bitstream/10183/259834/1/001168979.pdf",
            "http://dx.doi.org/10.1371/journal.pone.0276202",
        ],
    }

    selected = source._select_best_pdf_url(work)
    assert selected == "https://lume.ufrgs.br/bitstream/10183/259834/1/001168979.pdf"


def test_core_falls_back_to_download_url_when_no_better_candidate():
    source = CORESource(api_key=None, timeout=5)
    source.session = _StubSession(
        {
            "https://doi.org/10.1234/abc": _StubResponse(
                status_code=200,
                content_type="text/html",
                body=b"<!DOCTYPE html>",
            ),
            "https://core.ac.uk/download/1234.pdf": _StubResponse(
                status_code=403,
                content_type="text/html",
                body=b"",
            ),
        }
    )
    work = {
        "downloadUrl": "https://core.ac.uk/download/1234.pdf",
        "sourceFulltextUrls": ["https://doi.org/10.1234/abc"],
    }

    selected = source._select_best_pdf_url(work)
    assert selected == "https://core.ac.uk/download/1234.pdf"


def test_core_probe_prefers_working_pdf_candidate():
    source = CORESource(api_key=None, timeout=5)
    source.session = _StubSession(
        {
            "https://papyrus.bib.umontreal.ca/xmlui/bitstream/1866/23242/1/peerj-06-4375.pdf": _StubResponse(
                status_code=200,
                content_type="text/html; charset=utf-8",
                body=b"<!DOCTYPE html>",
            ),
            "https://digitalcommons.unl.edu/cgi/viewcontent.cgi?article=1143&context=scholcom": _StubResponse(
                status_code=200,
                content_type="application/pdf",
                body=b"%PDF-1.5",
            ),
            "https://core.ac.uk/download/286364337.pdf": _StubResponse(
                status_code=403,
                content_type="text/html",
                body=b"",
            ),
        }
    )
    work = {
        "downloadUrl": "https://core.ac.uk/download/286364337.pdf",
        "sourceFulltextUrls": [
            "https://papyrus.bib.umontreal.ca/xmlui/bitstream/1866/23242/1/peerj-06-4375.pdf",
            "https://digitalcommons.unl.edu/cgi/viewcontent.cgi?article=1143&context=scholcom",
        ],
    }

    selected = source._select_best_pdf_url(work)
    assert (
        selected
        == "https://digitalcommons.unl.edu/cgi/viewcontent.cgi?article=1143&context=scholcom"
    )


def test_core_normalizes_html_escaped_candidate_urls():
    source = CORESource(api_key=None, timeout=5)
    source.session = _StubSession(
        {
            "https://digitalcommons.unl.edu/cgi/viewcontent.cgi?article=1143&context=scholcom": _StubResponse(
                status_code=200,
                content_type="application/pdf",
                body=b"%PDF-1.5",
            ),
            "https://core.ac.uk/download/286364337.pdf": _StubResponse(
                status_code=403,
                content_type="text/html",
                body=b"",
            ),
        }
    )
    work = {
        "downloadUrl": "https://core.ac.uk/download/286364337.pdf",
        "sourceFulltextUrls": [
            "https://digitalcommons.unl.edu/cgi/viewcontent.cgi?article=1143&amp;context=scholcom",
        ],
    }

    selected = source._select_best_pdf_url(work)
    assert (
        selected
        == "https://digitalcommons.unl.edu/cgi/viewcontent.cgi?article=1143&context=scholcom"
    )
