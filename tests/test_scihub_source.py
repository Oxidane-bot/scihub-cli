from scihub_cli.core.doi_processor import DOIProcessor
from scihub_cli.core.parser import ContentParser
from scihub_cli.sources.scihub_source import SciHubSource


class _StubMirrorManager:
    def __init__(self, mirrors):
        self.mirrors = mirrors
        self.failed = []

    def get_working_mirror(self):
        return self.mirrors[0]

    def mark_failed(self, mirror):
        self.failed.append(mirror)

    def invalidate_cache(self):
        return None


class _StubDownloader:
    def __init__(self, url_to_response):
        self.url_to_response = url_to_response

    def get_page_content(self, url):
        return self.url_to_response.get(url, (None, None))


def test_scihub_source_switches_mirrors_on_failure():
    mirrors = ["https://m1.test", "https://m2.test"]
    doi = "10.1234/abcd"
    formatted = DOIProcessor.format_doi_for_url(doi)

    html = """
    <html><body>
      <iframe id="pdf" src="/downloads/10.1234/abcd.pdf"></iframe>
    </body></html>
    """
    responses = {
        f"{mirrors[0]}/{formatted}": ("Forbidden", 403),
        f"{mirrors[0]}/{doi}": ("Forbidden", 403),
        f"{mirrors[1]}/{formatted}": (html, 200),
    }

    mirror_manager = _StubMirrorManager(mirrors)
    downloader = _StubDownloader(responses)

    source = SciHubSource(
        mirror_manager=mirror_manager,
        parser=ContentParser(),
        doi_processor=DOIProcessor(),
        downloader=downloader,
    )

    url = source.get_pdf_url(doi)
    assert url == "https://m2.test/downloads/10.1234/abcd.pdf?download=true"
    assert mirror_manager.failed == [mirrors[0]]
