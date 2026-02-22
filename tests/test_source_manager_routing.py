from __future__ import annotations

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


def test_source_manager_routes_non_url_arxiv_identifier_to_oa_chain():
    sources = [
        _StubSource("arXiv", can_handle_result=True),
        _StubSource("Unpaywall"),
        _StubSource("CORE"),
        _StubSource("Sci-Hub"),
    ]
    manager = SourceManager(sources=sources, enable_year_routing=False)

    chain = manager.get_source_chain("arXiv:1202.2745")

    assert [source.name for source in chain] == ["arXiv", "Unpaywall", "CORE", "Sci-Hub"]
