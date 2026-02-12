from scihub_cli.core.pdf_link_extractor import extract_pdf_candidates


def test_extract_cloudflare_challenge_token_candidate():
    base_url = "https://files01.core.ac.uk/download/286364337.pdf"
    html = (
        '<html><script>'
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
