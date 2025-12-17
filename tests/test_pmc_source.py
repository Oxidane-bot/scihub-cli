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
