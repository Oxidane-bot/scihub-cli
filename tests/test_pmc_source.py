from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch

from scihub_cli.sources.europe_pmc_common import EuropePMCHostThrottle
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


def test_pmc_page_retry_honors_retry_after_without_rotating_hosts():
    class _RateLimitedDownloader:
        def __init__(self):
            self.calls = 0
            self.headers = [{"Retry-After": "4"}, {}]

        def get_page_content(self, url: str):  # noqa: ARG002
            self.calls += 1
            if self.calls == 1:
                return "Rate limited", 429
            return (
                '<meta name="citation_pdf_url" content="https://pmc.example/paper.pdf">',
                200,
            )

        def get_last_page_response_headers(self):
            return self.headers[min(self.calls - 1, len(self.headers) - 1)]

        def probe_pdf_url(self, url: str):  # noqa: ARG002
            raise AssertionError("A successful page should not probe alternate hosts")

    downloader = _RateLimitedDownloader()
    source = PMCSource(downloader=downloader)  # type: ignore[arg-type]
    EuropePMCHostThrottle.reset_for_tests()

    with patch("scihub_cli.sources.pmc_source.time.sleep") as sleep:
        url = source.get_pdf_url("https://pmc.ncbi.nlm.nih.gov/articles/PMC6505544/")

    assert url == "https://pmc.example/paper.pdf"
    assert downloader.calls == 2
    assert any(call.args[0] >= 3.9 for call in sleep.call_args_list)
    EuropePMCHostThrottle.reset_for_tests()


def test_pmc_does_not_sleep_on_an_over_budget_retry_after():
    class _HugeRateLimitedDownloader:
        def __init__(self):
            self.calls = 0

        def get_page_content(self, url: str):  # noqa: ARG002
            self.calls += 1
            return "Rate limited", 429

        def get_last_page_response_headers(self):
            return {"Retry-After": "1e300"}

    downloader = _HugeRateLimitedDownloader()
    source = PMCSource(downloader=downloader)  # type: ignore[arg-type]
    EuropePMCHostThrottle.reset_for_tests()

    with patch("scihub_cli.sources.pmc_source.time.sleep") as sleep:
        assert source.get_pdf_url("https://pmc.ncbi.nlm.nih.gov/articles/PMC6505544/") is None

    assert downloader.calls == 1
    sleep.assert_not_called()
    EuropePMCHostThrottle.reset_for_tests()
