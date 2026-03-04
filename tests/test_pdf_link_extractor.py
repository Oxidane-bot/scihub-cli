from scihub_cli.core.pdf_link_extractor import (
    derive_publisher_pdf_candidates,
    extract_pdf_candidates,
    extract_ranked_pdf_candidates,
)


def test_extract_cloudflare_challenge_token_candidate_is_filtered_out():
    base_url = "https://files01.core.ac.uk/download/286364337.pdf"
    html = (
        "<html><script>"
        'window._cf_chl_opt={cUPMDTk:"\\/download\\/286364337.pdf?__cf_chl_tk=abc"};'
        "</script></html>"
    )

    candidates = extract_pdf_candidates(html, base_url, min_score=1)

    assert "https://files01.core.ac.uk/download/286364337.pdf?__cf_chl_tk=abc" not in candidates


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


def test_mdpi_suspicious_path_does_not_generate_prefetch_pdf_candidate():
    candidates = derive_publisher_pdf_candidates("https://www.mdpi.com/about/journals/proposal)[x")
    assert "https://www.mdpi.com/about/journals/proposal)[x/pdf" not in candidates


def test_mdpi_redirect_new_site_generates_canonical_pdf_candidate():
    candidates = derive_publisher_pdf_candidates(
        "https://www.mdpi.com/redirect/new_site?return=/2227-9717/11/7/1982"
    )
    assert "https://www.mdpi.com/2227-9717/11/7/1982/pdf" in candidates


def test_mdpi_non_article_paths_do_not_generate_pdf_candidate():
    candidates = derive_publisher_pdf_candidates("https://www.mdpi.com/journal/energies")
    assert not any(url.startswith("https://www.mdpi.com/journal/energies") for url in candidates)


def test_derive_adsabs_pub_html_candidate():
    candidates = derive_publisher_pdf_candidates(
        "https://ui.adsabs.harvard.edu/abs/2017AIPC.1850p0024R/abstract"
    )
    assert "https://ui.adsabs.harvard.edu/link_gateway/2017AIPC.1850p0024R/PUB_HTML" in candidates


def test_extracted_candidate_trims_trailing_junk():
    base_url = "https://example.org/article"
    html = """
    <html><body>
      <a href="/download/paper.pdf}}">Download PDF</a>
    </body></html>
    """
    candidates = extract_pdf_candidates(html, base_url, min_score=1)
    assert "https://example.org/download/paper.pdf" in candidates


def test_auth_or_paywall_urls_are_filtered_out():
    base_url = "https://example.org/article"
    html = """
    <html><body>
      <a href="/login?next=/paper.pdf">Login</a>
      <a href="/purchase?item=paper.pdf">Purchase</a>
      <a href="/download/paper.pdf">Download PDF</a>
    </body></html>
    """
    candidates = extract_pdf_candidates(html, base_url, min_score=1)
    assert "https://example.org/login?next=/paper.pdf" not in candidates
    assert "https://example.org/purchase?item=paper.pdf" not in candidates
    assert "https://example.org/download/paper.pdf" in candidates


def test_pdf_tail_path_without_pdf_extension_is_ranked():
    base_url = "https://www.frontiersin.org/articles/10.3389/fenrg.2021.627864/full"
    html = """
    <html><body>
      <script>
        window.__ARTICLE__ = {"pdfUrl":"https://www.frontiersin.org/articles/10.3389/fenrg.2021.627864/pdf"};
      </script>
    </body></html>
    """
    ranked = extract_ranked_pdf_candidates(html, base_url)
    urls = [url for _, url in ranked]
    assert "https://www.frontiersin.org/articles/10.3389/fenrg.2021.627864/pdf" in urls


def test_tracker_iframe_candidate_is_filtered_even_with_embed_bonus():
    base_url = "https://example.org/article"
    html = """
    <html><body>
      <iframe src="https://www.googletagmanager.com/ns.html?id=GTM-NT2453N"></iframe>
      <iframe src="https://cdn.example.org/content/paper.pdf"></iframe>
    </body></html>
    """
    ranked = extract_ranked_pdf_candidates(html, base_url)
    urls = [url for _, url in ranked]
    assert "https://www.googletagmanager.com/ns.html?id=GTM-NT2453N" not in urls
    assert "https://cdn.example.org/content/paper.pdf" in urls


def test_inline_concatenated_markdown_url_keeps_pdf_url():
    base_url = "https://example.org/article"
    html = """
    <html><body>
      <a href="https://cdn.example.org/paper.pdf)](https://www.mdpi.com/books)">Download</a>
    </body></html>
    """
    candidates = extract_pdf_candidates(html, base_url, min_score=1)
    assert "https://cdn.example.org/paper.pdf" in candidates
