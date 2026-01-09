from __future__ import annotations

from dataclasses import dataclass

from scihub_cli.sources.pmc_source import PMCSource


@dataclass
class _StubDownloader:
    html: str
    status: int = 200

    def get_page_content(self, url: str) -> tuple[str | None, int | None]:  # noqa: ARG002
        return self.html, self.status


def test_pmc_extracts_pdf_from_citation_meta():
    html = """
    <html><head>
      <meta name="citation_pdf_url" content="https://pmc.ncbi.nlm.nih.gov/articles/PMC6505544/pdf/foo.pdf" />
    </head><body></body></html>
    """
    source = PMCSource(downloader=_StubDownloader(html=html))  # type: ignore[arg-type]
    url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC6505544/"
    assert source.get_pdf_url(url) == "https://pmc.ncbi.nlm.nih.gov/articles/PMC6505544/pdf/foo.pdf"


def test_pmc_extracts_pdf_from_relative_link():
    html = """
    <html><body>
      <a class="pmc-pdf-download" href="/articles/PMC6505544/pdf/bar.pdf">PDF</a>
    </body></html>
    """
    source = PMCSource(downloader=_StubDownloader(html=html))  # type: ignore[arg-type]
    url = "https://pmc.ncbi.nlm.nih.gov/articles/PMC6505544/"
    assert source.get_pdf_url(url) == "https://pmc.ncbi.nlm.nih.gov/articles/PMC6505544/pdf/bar.pdf"


def test_pmc_accepts_pdf_like_urls_directly():
    html = "<html></html>"
    source = PMCSource(downloader=_StubDownloader(html=html))  # type: ignore[arg-type]
    url = "https://europepmc.org/articles/PMC6505544?pdf=render#fragment"
    assert source.get_pdf_url(url) == "https://europepmc.org/articles/PMC6505544?pdf=render"


def test_pmc_fallback_uses_probe():
    class _ProbeDownloader:
        def __init__(self, ok_urls: set[str]):
            self.ok_urls = ok_urls
            self.probed: list[str] = []

        def get_page_content(self, url: str) -> tuple[str | None, int | None]:  # noqa: ARG002
            return None, None

        def probe_pdf_url(self, url: str) -> bool:
            self.probed.append(url)
            return url in self.ok_urls

    pmc_id = "PMC6505544"
    first = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/pdf/"
    second = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/pdf/"

    downloader = _ProbeDownloader(ok_urls={second})
    source = PMCSource(downloader=downloader)  # type: ignore[arg-type]
    url = f"https://pmc.ncbi.nlm.nih.gov/articles/{pmc_id}/"

    assert source.get_pdf_url(url) == second
    assert downloader.probed[:2] == [first, second]
