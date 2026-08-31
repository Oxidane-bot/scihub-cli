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


def test_normalize_doi_keeps_invalid_doi_org_url():
    identifier = "https://doi.org/10.1016"
    assert DOIProcessor.normalize_doi(identifier) == identifier


def test_normalize_doi_trims_trailing_noise_from_doi_url():
    assert DOIProcessor.normalize_doi("https://doi.org/10.1016/j.rser.2021.111658}}") == (
        "10.1016/j.rser.2021.111658"
    )


def test_normalize_doi_trims_trailing_noise_from_raw_doi():
    assert DOIProcessor.normalize_doi("10.1080/14606925.2016.1130956],") == (
        "10.1080/14606925.2016.1130956"
    )


def test_normalize_doi_strips_markdown_concatenation_tail():
    identifier = (
        "https://doi.org/10.1016/j.applthermaleng.2016.04.055]"
        "(https://doi.org/10.1016/j.applthermaleng.2016.04.055"
    )
    assert DOIProcessor.normalize_doi(identifier) == "10.1016/j.applthermaleng.2016.04.055"


def test_normalize_doi_fixes_underscore_separator_corruption():
    assert DOIProcessor.normalize_doi("https://doi.org/10.1177_00222429241299477") == (
        "10.1177/00222429241299477"
    )


def test_normalize_doi_trims_concatenated_prose_tail():
    assert DOIProcessor.normalize_doi("https://doi.org/10.1002/wene.420Digital") == (
        "10.1002/wene.420"
    )


def test_normalize_non_doi_url_canonicalizes_noise():
    raw = "https://www.mdpi.com/1996-1073/12/15/2930/?utm_source=test&download=true#related"
    assert DOIProcessor.normalize_doi(raw) == "https://mdpi.com/1996-1073/12/15/2930?download=true"


def test_normalize_non_doi_url_strips_fragment_tail_noise():
    raw = "https://pmc.ncbi.nlm.nih.gov/articles/PMC11021330/#}["
    assert DOIProcessor.normalize_doi(raw) == "https://pmc.ncbi.nlm.nih.gov/articles/PMC11021330"


def test_normalize_crossref_api_works_url_to_doi():
    raw = "https://api.crossref.org/works/10.1007%2Fs10584-018-2272-5"
    assert DOIProcessor.normalize_doi(raw) == "10.1007/s10584-018-2272-5"


def test_extract_pmc_id_accepts_only_bare_or_trusted_article_urls():
    accepted = {
        "PMC6505544": "PMC6505544",
        "https://pmc.ncbi.nlm.nih.gov/articles/PMC6505544/": "PMC6505544",
        "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6505544/pdf/main.pdf": "PMC6505544",
        "https://europepmc.org/articles/PMC6505544?pdf=render": "PMC6505544",
        "https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC6505544&blobtype=pdf": "PMC6505544",
    }

    for identifier, expected in accepted.items():
        assert DOIProcessor.extract_pmc_id(identifier) == expected


def test_extract_pmc_id_rejects_untrusted_query_path_and_doi_tokens():
    rejected = [
        "paper PMC6505544",
        "https://downloads.example.test/paper.pdf?pmcid=PMC6505544",
        "https://downloads.example.test/articles/PMC6505544/paper.pdf",
        "https://doi.org/10.1234/PMC6505544",
        "https://publisher.example/doi/10.1234/PMC6505544",
        "https://pmc.ncbi.nlm.nih.gov/search?query=PMC6505544",
        "https://europepmc.org/search?query=PMC6505544",
    ]

    assert all(DOIProcessor.extract_pmc_id(identifier) is None for identifier in rejected)


def test_normalize_identifier_prefers_doi_over_pmc_token_in_url():
    variants = [
        "https://doi.org/10.1234/PMC6505544",
        "https://publisher.example/doi/10.1234/PMC6505544",
    ]

    assert {DOIProcessor.normalize_identifier(value) for value in variants} == {
        "10.1234/pmc6505544"
    }
