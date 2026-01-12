import sys
import types

from scihub_cli.core.downloader import FileDownloader


class _StubResponse:
    def __init__(self, status_code=200, text="", headers=None, content=b""):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}
        self._content = content

    def iter_content(self, chunk_size=8192):
        if not self._content:
            return
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]


class _ForbiddenSession:
    def get(self, url, timeout=None, stream=False):  # noqa: ARG002
        return _StubResponse(
            status_code=403,
            text="Forbidden",
            headers={"Content-Type": "text/html"},
        )


def test_get_page_content_cloudscraper_fallback(monkeypatch):
    downloader = FileDownloader(session=_ForbiddenSession(), timeout=5)

    def _create_scraper():
        class _Scraper:
            def get(self, url, timeout=None):  # noqa: ARG002
                return _StubResponse(
                    status_code=200,
                    text="OK",
                    headers={"Content-Type": "text/html"},
                )

        return _Scraper()

    monkeypatch.setitem(
        sys.modules, "cloudscraper", types.SimpleNamespace(create_scraper=_create_scraper)
    )

    html, status = downloader.get_page_content("https://example.org")
    assert status == 200
    assert html == "OK"


def test_download_file_cloudscraper_fallback(tmp_path, monkeypatch):
    downloader = FileDownloader(session=_ForbiddenSession(), timeout=5)
    pdf_bytes = b"%PDF-1.4\\n1 0 obj\\n<<>>\\nendobj\\n%%EOF\\n"

    def _create_scraper():
        class _Scraper:
            def get(self, url, timeout=None, stream=True):  # noqa: ARG002
                return _StubResponse(
                    status_code=200,
                    headers={
                        "Content-Type": "application/pdf",
                        "Content-Length": str(len(pdf_bytes)),
                    },
                    content=pdf_bytes,
                )

        return _Scraper()

    monkeypatch.setitem(
        sys.modules, "cloudscraper", types.SimpleNamespace(create_scraper=_create_scraper)
    )

    output = tmp_path / "paper.pdf"
    success, error = downloader.download_file("https://example.org/paper.pdf", str(output))
    assert success, error
    assert output.read_bytes()[:4] == b"%PDF"
