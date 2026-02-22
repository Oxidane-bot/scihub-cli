from scihub_cli.core.pdf_link_extractor import (
    derive_publisher_pdf_candidates,
    extract_pdf_candidates,
    extract_ranked_pdf_candidates,
)


def test_extract_cloudflare_challenge_token_candidate():
    base_url = "https://files01.core.ac.uk/download/286364337.pdf"
    html = (
        "<html><script>"
        'window._cf_chl_opt={cUPMDTk:"\\/download\\/286364337.pdf?__cf_chl_tk=abc"};'
        "</script></html>"
    )

    candidates = extract_pdf_candidates(html, base_url, min_score=1)

    assert "https://files01.core.ac.uk/download/286364337.pdf?__cf_chl_tk=abc" in candidates


def test_extract_drupal_settings_pdf_candidate():
    base_url = "https://summit.sfu.ca/system/files/iritems1/17691/peerj-4375.pdf"
    html = """
    <html><body>
      <script type="application/json" data-drupal-selector="drupal-settings-json">
      {"path":{"currentPath":"system/files","currentQuery":{"file":"iritems1/17691/peerj-4375.pdf"}}}
      </script>
    </body></html>
    """

    candidates = extract_pdf_candidates(html, base_url, min_score=1)

    assert "https://summit.sfu.ca/system/files?file=iritems1%2F17691%2Fpeerj-4375.pdf" in candidates


def test_extract_entity_encoded_script_pdf_url_candidate():
    base_url = "https://example.org/article"
    html = """
    <html><body>
      <script>
        window.__ARTICLE__ = {"pdfUrl":"https&#58;&#47;&#47;cdn.example.org&#47;papers&#47;abc-123.pdf"};
      </script>
    </body></html>
    """

    candidates = extract_pdf_candidates(html, base_url, min_score=1)

    assert "https://cdn.example.org/papers/abc-123.pdf" in candidates


def test_extract_sciencedirect_pdfft_candidates_from_pii_path():
    base_url = "https://www.sciencedirect.com/science/article/abs/pii/S1364032121006948"
    ranked = extract_ranked_pdf_candidates("<html></html>", base_url)
    candidates = [url for _, url in ranked]

    assert (
        "https://www.sciencedirect.com/science/article/pii/"
        "S1364032121006948/pdfft?isDTMRedir=true&download=true"
    ) in candidates
    assert (
        "https://www.sciencedirect.com/science/article/pii/S1364032121006948/pdfft"
    ) in candidates


def test_extract_publisher_derived_candidates():
    nature = extract_pdf_candidates(
        "<html></html>",
        "https://www.nature.com/articles/s41598-024-75283-7",
        min_score=1,
    )
    tandf = extract_pdf_candidates(
        "<html></html>",
        "https://www.tandfonline.com/doi/abs/10.1080/14606925.2016.1130956",
        min_score=1,
    )
    mdpi = extract_pdf_candidates(
        "<html></html>",
        "https://www.mdpi.com/2071-1050/15/20/14828",
        min_score=1,
    )
    arxiv = extract_pdf_candidates(
        "<html></html>",
        "https://arxiv.org/html/2502.11082v1",
        min_score=1,
    )

    assert "https://www.nature.com/articles/s41598-024-75283-7.pdf" in nature
    assert "https://www.tandfonline.com/doi/pdf/10.1080/14606925.2016.1130956" in tandf
    assert "https://www.mdpi.com/2071-1050/15/20/14828/pdf" in mdpi
    assert "https://arxiv.org/pdf/2502.11082v1.pdf" in arxiv


def test_tracker_url_is_filtered_out_of_ranked_candidates():
    base_url = "https://example.org/article"
    html = """
    <html><body>
      <a href="https://www.googletagmanager.com/ns.html?id=GTM-NT2453N">tracking</a>
      <a href="/download/paper.pdf">Download PDF</a>
    </body></html>
    """

    ranked = extract_ranked_pdf_candidates(html, base_url)
    urls = [url for _, url in ranked]

    assert "https://www.googletagmanager.com/ns.html?id=GTM-NT2453N" not in urls
    assert "https://example.org/download/paper.pdf" in urls


def test_non_pdf_asset_url_is_filtered_out_of_ranked_candidates():
    base_url = "https://example.org/article"
    html = """
    <html><body>
      <a href="https://cdn.example.org/wp-content/uploads/TBJ-White-15.png">Download</a>
      <a href="/download/paper.pdf">Download PDF</a>
    </body></html>
    """

    ranked = extract_ranked_pdf_candidates(html, base_url)
    urls = [url for _, url in ranked]

    assert "https://cdn.example.org/wp-content/uploads/TBJ-White-15.png" not in urls
    assert "https://example.org/download/paper.pdf" in urls


def test_derive_publisher_candidates_without_html():
    candidates = derive_publisher_pdf_candidates(
        "https://www.nature.com/articles/s41598-024-75283-7"
    )
    assert "https://www.nature.com/articles/s41598-024-75283-7.pdf" in candidates
