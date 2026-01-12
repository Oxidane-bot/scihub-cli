from scihub_cli.core.parser import ContentParser


def test_content_parser_unescapes_iframe_src():
    html = """
    <html><body>
      <iframe id="pdf" src="https:\\/\\/sci.bban.top\\/pdf/10.1145/1390156.1390177.pdf"></iframe>
    </body></html>
    """
    parser = ContentParser()
    url = parser.extract_download_url(html, "https://sci.bban.top")
    assert url == "https://sci.bban.top/pdf/10.1145/1390156.1390177.pdf?download=true"


def test_content_parser_iframe_without_id():
    html = """
    <html><body>
      <iframe src="/downloads/10.1145/1390156.1390177.pdf"></iframe>
    </body></html>
    """
    parser = ContentParser()
    url = parser.extract_download_url(html, "https://sci-hub.ren")
    assert url == "https://sci-hub.ren/downloads/10.1145/1390156.1390177.pdf?download=true"
