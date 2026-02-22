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
    def __init__(self, url_to_response, *, fast_fail=False):
        self.url_to_response = url_to_response
        self.fast_fail = fast_fail
        self.calls = []
        self.call_kwargs = []

    def get_page_content(self, url, **kwargs):
        self.calls.append(url)
        self.call_kwargs.append(kwargs)
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


def test_scihub_source_fast_fail_limits_mirror_attempts_and_skips_fallback():
    mirrors = ["https://m1.test", "https://m2.test", "https://m3.test"]
    doi = "10.1234/abcd"
    formatted = DOIProcessor.format_doi_for_url(doi)

    no_pdf_html = "<html><body>no pdf here</body></html>"
    success_html = """
    <html><body>
      <iframe id="pdf" src="/downloads/10.1234/abcd.pdf"></iframe>
    </body></html>
    """
    responses = {
        f"{mirrors[0]}/{formatted}": (no_pdf_html, 200),
        f"{mirrors[0]}/{doi}": (no_pdf_html, 200),
        f"{mirrors[1]}/{formatted}": (no_pdf_html, 200),
        f"{mirrors[1]}/{doi}": (no_pdf_html, 200),
        f"{mirrors[2]}/{formatted}": (success_html, 200),
    }

    mirror_manager = _StubMirrorManager(mirrors)
    downloader = _StubDownloader(responses, fast_fail=True)

    source = SciHubSource(
        mirror_manager=mirror_manager,
        parser=ContentParser(),
        doi_processor=DOIProcessor(),
        downloader=downloader,
    )

    url = source.get_pdf_url(doi)
    assert url is None
    assert downloader.calls == [
        f"{mirrors[0]}/{formatted}",
        f"{mirrors[1]}/{formatted}",
    ]


def test_scihub_source_fast_fail_skips_status_fallback_to_raw_doi():
    mirrors = ["https://m1.test"]
    doi = "10.1234/abcd"
    formatted = DOIProcessor.format_doi_for_url(doi)

    success_html = """
    <html><body>
      <iframe id="pdf" src="/downloads/10.1234/abcd.pdf"></iframe>
    </body></html>
    """
    responses = {
        f"{mirrors[0]}/{formatted}": ("Forbidden", 403),
        f"{mirrors[0]}/{doi}": (success_html, 200),
    }

    mirror_manager = _StubMirrorManager(mirrors)
    downloader = _StubDownloader(responses, fast_fail=True)
    source = SciHubSource(
        mirror_manager=mirror_manager,
        parser=ContentParser(),
        doi_processor=DOIProcessor(),
        downloader=downloader,
    )

    url = source.get_pdf_url(doi)
    assert url is None
    assert downloader.calls == [f"{mirrors[0]}/{formatted}"]


def test_scihub_source_fast_fail_uses_page_timeout_override():
    mirrors = ["https://m1.test"]
    doi = "10.1234/abcd"
    formatted = DOIProcessor.format_doi_for_url(doi)
    responses = {f"{mirrors[0]}/{formatted}": ("<html>no pdf</html>", 200)}

    mirror_manager = _StubMirrorManager(mirrors)
    downloader = _StubDownloader(responses, fast_fail=True)
    source = SciHubSource(
        mirror_manager=mirror_manager,
        parser=ContentParser(),
        doi_processor=DOIProcessor(),
        downloader=downloader,
    )

    _ = source.get_pdf_url(doi)
    assert downloader.calls == [f"{mirrors[0]}/{formatted}"]
    assert downloader.call_kwargs
    timeout = downloader.call_kwargs[0].get("timeout_seconds")
    assert isinstance(timeout, float)
    assert 1.0 <= timeout <= source._FAST_FAIL_PAGE_TIMEOUT_SECONDS


def test_scihub_source_fast_fail_rescue_doi_allows_status_fallback_and_bypass():
    mirrors = ["https://m1.test"]
    doi = "10.1016/j.applthermaleng.2021.116919"
    formatted = DOIProcessor.format_doi_for_url(doi)
    success_html = """
    <html><body>
      <iframe id="pdf" src="/downloads/10.1016/j.applthermaleng.2021.116919.pdf"></iframe>
    </body></html>
    """
    responses = {
        f"{mirrors[0]}/{formatted}": ("Forbidden", 403),
        f"{mirrors[0]}/{doi}": (success_html, 200),
    }

    mirror_manager = _StubMirrorManager(mirrors)
    downloader = _StubDownloader(responses, fast_fail=True)
    source = SciHubSource(
        mirror_manager=mirror_manager,
        parser=ContentParser(),
        doi_processor=DOIProcessor(),
        downloader=downloader,
    )

    url = source.get_pdf_url(doi)
    assert url == "https://m1.test/downloads/10.1016/j.applthermaleng.2021.116919.pdf?download=true"
    assert downloader.calls == [f"{mirrors[0]}/{formatted}", f"{mirrors[0]}/{doi}"]
    assert downloader.call_kwargs[0].get("force_challenge_bypass") is True
    assert downloader.call_kwargs[1].get("force_challenge_bypass") is True
    timeout = downloader.call_kwargs[0].get("timeout_seconds")
    assert isinstance(timeout, float)
    assert 1.0 <= timeout <= source._FAST_FAIL_RESCUE_PAGE_TIMEOUT_SECONDS


def test_scihub_source_fast_fail_rescue_doi_can_use_third_mirror():
    mirrors = ["https://m1.test", "https://m2.test", "https://m3.test"]
    doi = "10.1080/09593969.2015.1017773"
    formatted = DOIProcessor.format_doi_for_url(doi)
    success_html = """
    <html><body>
      <iframe id="pdf" src="/downloads/10.1080/09593969.2015.1017773.pdf"></iframe>
    </body></html>
    """
    responses = {
        f"{mirrors[0]}/{formatted}": ("<html>no pdf</html>", 200),
        f"{mirrors[1]}/{formatted}": ("<html>still no pdf</html>", 200),
        f"{mirrors[2]}/{formatted}": (success_html, 200),
    }

    mirror_manager = _StubMirrorManager(mirrors)
    downloader = _StubDownloader(responses, fast_fail=True)
    source = SciHubSource(
        mirror_manager=mirror_manager,
        parser=ContentParser(),
        doi_processor=DOIProcessor(),
        downloader=downloader,
    )

    url = source.get_pdf_url(doi)
    assert url == "https://m3.test/downloads/10.1080/09593969.2015.1017773.pdf?download=true"
    assert downloader.calls == [
        f"{mirrors[0]}/{formatted}",
        f"{mirrors[0]}/{doi}",
        f"{mirrors[1]}/{formatted}",
        f"{mirrors[1]}/{doi}",
        f"{mirrors[2]}/{formatted}",
    ]


def test_scihub_source_fast_fail_rescue_doi_can_fallback_after_no_result_200():
    mirrors = ["https://m1.test"]
    doi = "10.1080/09593969.2015.1017773"
    formatted = DOIProcessor.format_doi_for_url(doi)
    success_html = """
    <html><body>
      <iframe id="pdf" src="/downloads/10.1080/09593969.2015.1017773.pdf"></iframe>
    </body></html>
    """
    responses = {
        f"{mirrors[0]}/{formatted}": ("<html>no pdf here</html>", 200),
        f"{mirrors[0]}/{doi}": (success_html, 200),
    }

    mirror_manager = _StubMirrorManager(mirrors)
    downloader = _StubDownloader(responses, fast_fail=True)
    source = SciHubSource(
        mirror_manager=mirror_manager,
        parser=ContentParser(),
        doi_processor=DOIProcessor(),
        downloader=downloader,
    )

    url = source.get_pdf_url(doi)
    assert url == "https://m1.test/downloads/10.1080/09593969.2015.1017773.pdf?download=true"
    assert downloader.calls == [f"{mirrors[0]}/{formatted}", f"{mirrors[0]}/{doi}"]


def test_scihub_source_fast_fail_rescue_reorders_tail_mirrors_by_hint():
    mirrors = [
        "https://sci-hub.ren",
        "https://sci-hub.vg",
        "https://sci-hub.mk",
        "https://sci-hub.ee",
    ]
    doi = "10.1080/09593969.2015.1017773"
    formatted = DOIProcessor.format_doi_for_url(doi)
    success_html = """
    <html><body>
      <iframe id="pdf" src="/downloads/10.1080/09593969.2015.1017773.pdf"></iframe>
    </body></html>
    """
    responses = {
        f"{mirrors[0]}/{formatted}": ("<html>no pdf</html>", 200),
        f"{mirrors[0]}/{doi}": ("<html>still no pdf</html>", 200),
        f"{mirrors[1]}/{formatted}": ("<html>no pdf</html>", 200),
        f"{mirrors[1]}/{doi}": ("<html>still no pdf</html>", 200),
        f"{mirrors[2]}/{formatted}": (success_html, 200),
    }

    mirror_manager = _StubMirrorManager(mirrors)
    downloader = _StubDownloader(responses, fast_fail=True)
    source = SciHubSource(
        mirror_manager=mirror_manager,
        parser=ContentParser(),
        doi_processor=DOIProcessor(),
        downloader=downloader,
    )

    url = source.get_pdf_url(doi)
    assert url == "https://sci-hub.mk/downloads/10.1080/09593969.2015.1017773.pdf?download=true"
    assert downloader.calls == [
        f"{mirrors[0]}/{formatted}",
        f"{mirrors[0]}/{doi}",
        f"{mirrors[1]}/{formatted}",
        f"{mirrors[1]}/{doi}",
        f"{mirrors[2]}/{formatted}",
    ]
