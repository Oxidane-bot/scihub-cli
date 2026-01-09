from scihub_cli.sources.arxiv_source import ArxivSource


def test_arxiv_can_handle_urls():
    source = ArxivSource(timeout=5)

    assert source.can_handle("https://arxiv.org/abs/1202.2745")
    assert source.can_handle("https://arxiv.org/abs/1202.2745v2")
    assert source.can_handle("https://arxiv.org/pdf/1202.2745.pdf")
