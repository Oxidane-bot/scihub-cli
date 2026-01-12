from scihub_cli.core.doi_processor import DOIProcessor


def test_normalize_doi_strips_prefix():
    assert DOIProcessor.normalize_doi("doi:10.1000/xyz") == "10.1000/xyz"
    assert DOIProcessor.normalize_doi("DOI: 10.1000/xyz") == "10.1000/xyz"
    assert DOIProcessor.normalize_doi("doi 10.1000/xyz") == "10.1000/xyz"


def test_normalize_doi_removes_internal_whitespace():
    assert (
        DOIProcessor.normalize_doi("https://arxiv.org/\n abs/1706.03762")
        == "https://arxiv.org/abs/1706.03762"
    )
    assert DOIProcessor.normalize_doi("10.1000/ xyz") == "10.1000/xyz"


def test_normalize_doi_from_url():
    assert DOIProcessor.normalize_doi("https://doi.org/10.1000/xyz") == "10.1000/xyz"
