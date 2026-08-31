from __future__ import annotations

import threading

from scihub_cli.core.source_manager import SourceManager


class _StubSource:
    def __init__(self, name: str, *, can_handle_result: bool = False):
        self._name = name
        self._can_handle_result = can_handle_result

    @property
    def name(self) -> str:
        return self._name

    def can_handle(self, _identifier: str) -> bool:
        return self._can_handle_result

    def get_pdf_url(self, _identifier: str):
        return None


class _BlockingURLSource:
    def __init__(self, name: str, url: str, *, started: threading.Event | None = None):
        self._name = name
        self.url = url
        self.started = started
        self.release = threading.Event()
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def can_handle(self, _identifier: str) -> bool:
        return True

    def get_pdf_url(self, _identifier: str) -> str:
        self.calls += 1
        if self.started is not None:
            self.started.set()
            self.release.wait(timeout=2)
        return self.url


def test_source_manager_routes_arxiv_url_with_url_fallback_chain():
    sources = [
        _StubSource("Direct PDF"),
        _StubSource("PMC"),
        _StubSource("HTML Landing"),
        _StubSource("arXiv", can_handle_result=True),
    ]
    manager = SourceManager(sources=sources, enable_year_routing=False)

    chain = manager.get_source_chain("https://arxiv.org/html/1202.2745v2")

    assert [source.name for source in chain] == ["arXiv", "Direct PDF", "PMC", "HTML Landing"]


def test_source_manager_routes_arxiv_pdf_url_directly_without_arxiv_metadata():
    sources = [
        _StubSource("Direct PDF"),
        _StubSource("PMC"),
        _StubSource("HTML Landing"),
        _StubSource("arXiv", can_handle_result=True),
    ]
    manager = SourceManager(sources=sources, enable_year_routing=False)

    chain = manager.get_source_chain("https://arxiv.org/pdf/1706.03762.pdf")

    assert [source.name for source in chain] == ["Direct PDF"]


def test_source_manager_routes_arxiv_pdf_query_url_directly():
    sources = [_StubSource("Direct PDF"), _StubSource("arXiv", can_handle_result=True)]
    manager = SourceManager(sources=sources, enable_year_routing=False)

    chain = manager.get_source_chain("https://arxiv.org/pdf/1706.03762?download=.pdf")

    assert [source.name for source in chain] == ["Direct PDF"]


def test_source_manager_routes_non_url_arxiv_identifier_to_oa_chain():
    sources = [
        _StubSource("arXiv", can_handle_result=True),
        _StubSource("OpenAlex"),
        _StubSource("Unpaywall"),
        _StubSource("CORE"),
        _StubSource("Sci-Hub"),
    ]
    manager = SourceManager(sources=sources, enable_year_routing=False)

    chain = manager.get_source_chain("arXiv:1202.2745")

    assert [source.name for source in chain] == [
        "arXiv",
        "OpenAlex",
        "Unpaywall",
        "CORE",
        "Sci-Hub",
    ]


def test_source_manager_routes_bare_pmcid_to_pmc_then_europe_pmc():
    sources = [
        _StubSource("PMC"),
        _StubSource("Europe PMC"),
        _StubSource("Europe PMC OA"),
        _StubSource("OpenAIRE"),
        _StubSource("Sci-Hub"),
    ]
    manager = SourceManager(sources=sources, enable_year_routing=False)

    chain = manager.get_source_chain("PMC6505544")

    assert [source.name for source in chain] == [
        "PMC",
        "Europe PMC",
        "Europe PMC OA",
        "OpenAIRE",
        "Sci-Hub",
    ]


def test_source_manager_does_not_treat_pmc_token_in_doi_url_as_pmcid():
    sources = [
        _StubSource("PMC"),
        _StubSource("Europe PMC"),
        _StubSource("HTML Landing"),
    ]
    manager = SourceManager(sources=sources, enable_year_routing=False)

    # URL-specific routing remains available, but the identifier itself must
    # not enter the bare-PMCID branch merely because its DOI suffix contains
    # the letters ``PMC``.
    chain = manager.get_source_chain("https://doi.org/10.1234/PMC6505544")

    assert [source.name for source in chain] == ["PMC", "HTML Landing"]


def test_source_manager_adds_openaire_after_fast_oa_sources():
    sources = [
        _StubSource("OpenAlex", can_handle_result=True),
        _StubSource("OpenAIRE", can_handle_result=True),
        _StubSource("Sci-Hub", can_handle_result=True),
    ]
    manager = SourceManager(sources=sources, enable_year_routing=False)

    old_paper_chain = manager.get_source_chain("10.1234/example", year=2020)
    recent_paper_chain = manager.get_source_chain("10.1234/example", year=2024)

    assert [source.name for source in old_paper_chain] == ["OpenAlex", "OpenAIRE", "Sci-Hub"]
    assert [source.name for source in recent_paper_chain] == ["OpenAlex", "OpenAIRE"]


def test_parallel_query_retains_lower_priority_url_candidates():
    secondary_started = threading.Event()
    primary = _BlockingURLSource("OpenAlex", "https://openalex.example/paper.pdf")
    secondary = _BlockingURLSource(
        "Unpaywall",
        "https://unpaywall.example/paper.pdf",
        started=secondary_started,
    )
    manager = SourceManager(
        sources=[primary, secondary],
        enable_year_routing=False,
        max_workers=2,
    )
    result: dict[str, object] = {}

    def _query() -> None:
        result["value"] = manager.get_pdf_url_with_metadata_and_trace("10.1234/example")

    thread = threading.Thread(target=_query)
    thread.start()
    assert secondary_started.wait(timeout=1)

    # Returning OpenAlex early would discard the in-flight Unpaywall result.
    assert "value" not in result
    secondary.release.set()
    thread.join(timeout=2)

    assert "value" in result
    pdf_url, _metadata, source, attempts = result["value"]  # type: ignore[misc]
    assert pdf_url == "https://openalex.example/paper.pdf"
    assert source == "OpenAlex"
    assert {attempt["source"] for attempt in attempts if attempt.get("pdf_url")} == {
        "OpenAlex",
        "Unpaywall",
    }
    assert secondary.calls == 1
