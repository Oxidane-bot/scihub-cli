"""Tests for OpenAireSource."""

from unittest.mock import MagicMock, patch

from scihub_cli.sources.openaire_source import OpenAireSource


def _make_json_response(data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.headers = {"Content-Type": "application/json"}
    return resp


def test_name():
    source = OpenAireSource(timeout=5)
    assert source.name == "OpenAIRE"


def test_can_handle_doi():
    source = OpenAireSource(timeout=5)
    assert source.can_handle("10.1234/test")


def test_cannot_handle_non_doi():
    source = OpenAireSource(timeout=5)
    assert not source.can_handle("arxiv:2301.00001")


def test_get_pdf_url_extracts_link():
    source = OpenAireSource(timeout=5)
    api_data = {
        "response": {
            "results": {
                "result": [
                    {
                        "metadata": {
                            "oaf:entity": {
                                "oaf:result": {
                                    "title": "Test Paper",
                                    "children": {
                                        "instance": [
                                            {
                                                "accessright": {
                                                    "classid": "OPEN",
                                                    "classname": "Open Access",
                                                },
                                                "webresource": [
                                                    {"url": "https://example.com/paper.pdf"}
                                                ],
                                            }
                                        ]
                                    },
                                }
                            }
                        }
                    }
                ]
            }
        }
    }
    mock_response = _make_json_response(api_data)

    with patch.object(source.session, "get", return_value=mock_response):
        url = source.get_pdf_url("10.1234/test")

    assert url == "https://example.com/paper.pdf"


def test_get_pdf_url_no_results():
    source = OpenAireSource(timeout=5)
    api_data = {"response": {"results": {"result": []}}}
    mock_response = _make_json_response(api_data)

    with patch.object(source.session, "get", return_value=mock_response):
        url = source.get_pdf_url("10.1234/nonexistent")

    assert url is None


def test_fast_fail_reduces_timeout():
    source = OpenAireSource(timeout=30, fast_fail=True)
    assert source.timeout <= 5


def test_get_pdf_url_prefers_exact_child_pid_and_parses_list_dollar_fields():
    source = OpenAireSource(timeout=5)
    api_data = {
        "response": {
            "results": {
                "result": [
                    {
                        "metadata": {
                            "oaf:entity": {
                                "oaf:result": {
                                    "title": [{"$": "Wrong neighboring record"}],
                                    "children": {
                                        "result": [
                                            {
                                                "pid": {"$": "10.1000/other"},
                                                "instance": {
                                                    "accessright": {"@classid": "OPEN"},
                                                    "webresource": {
                                                        "url": {
                                                            "$": "https://wrong.example/other.pdf"
                                                        }
                                                    },
                                                },
                                            },
                                            {
                                                "pid": {"$": "10.1000/target"},
                                                "instance": [
                                                    {
                                                        "accessright": {"@classid": "OPEN"},
                                                        "webresource": {
                                                            "url": {
                                                                "$": "https://repo.example/target.pdf"
                                                            }
                                                        },
                                                    }
                                                ],
                                                "title": {"$": "Exact target"},
                                            },
                                        ]
                                    },
                                }
                            }
                        }
                    }
                ]
            }
        }
    }

    with patch.object(source.session, "get", return_value=_make_json_response(api_data)):
        metadata = source.get_metadata("10.1000/target")

    assert metadata is not None
    assert metadata["pdf_url"] == "https://repo.example/target.pdf"
    assert metadata["is_oa"] is True


def test_openaire_extracts_title_and_year_from_list_dollar_fields():
    source = OpenAireSource(timeout=5)
    metadata = {
        "oaf:entity": {
            "oaf:result": {
                "title": [{"$": "A real title"}],
                "dateofacceptance": {"$": "2017-10-31"},
            }
        }
    }

    assert source._extract_title(metadata) == "A real title"
    assert source._extract_year(metadata) == 2017


def test_openaire_recognizes_pdf_endpoints_without_pdf_suffix():
    assert OpenAireSource._looks_like_pdf_url(
        "https://journals.plos.org/plosone/article/file?id=10.1000/target&type=printable"
    )
    assert OpenAireSource._looks_like_pdf_url("https://www.osti.gov/servlets/purl/1234567")
    assert not OpenAireSource._looks_like_pdf_url("ftp://repo.example/paper.pdf")


def test_openaire_prefers_child_exact_pid_over_related_parent_instance():
    source = OpenAireSource(timeout=5)
    metadata = {
        "oaf:entity": {
            "oaf:result": {
                "pid": [{"$": "10.1000/target"}, {"$": "10.1000/related"}],
                "children": {
                    "result": [
                        {
                            "pid": {"$": "10.1000/related"},
                            "instance": {
                                "accessright": {"@classid": "OPEN"},
                                "webresource": {"url": {"$": "https://repo.example/related.pdf"}},
                            },
                        },
                        {
                            "pid": {"$": "10.1000/target"},
                            "instance": {
                                "accessright": {"@classid": "OPEN"},
                                "webresource": {"url": {"$": "https://repo.example/target.pdf"}},
                            },
                        },
                    ]
                },
            }
        }
    }

    ranked = source._extract_ranked_urls(metadata, doi="10.1000/target")

    assert ranked[0] == ("https://repo.example/target.pdf", True)


def test_openaire_unwraps_children_instance_and_skips_ftp_candidates():
    source = OpenAireSource(timeout=5)
    metadata = {
        "oaf:entity": {
            "oaf:result": {
                "children": {
                    "instance": {
                        "instance": [
                            {
                                "accessright": {"@classid": "OPEN"},
                                "webresource": [
                                    {"url": {"$": "ftp://repo.example/paper.pdf"}},
                                    {"url": {"$": "https://repo.example/paper.pdf"}},
                                ],
                            }
                        ]
                    }
                }
            }
        }
    }

    ranked = source._extract_ranked_urls(metadata, doi="10.1000/target")

    assert ranked == [("https://repo.example/paper.pdf", True)]


def test_openaire_exact_landing_is_not_overridden_by_related_pdf():
    source = OpenAireSource(timeout=5)
    api_data = {
        "response": {
            "results": {
                "result": [
                    {
                        "metadata": {
                            "oaf:entity": {
                                "oaf:result": {
                                    "pid": [
                                        {"$": "10.1000/target"},
                                        {"$": "10.1000/related"},
                                    ],
                                    "children": {
                                        "result": [
                                            {
                                                "pid": {"$": "10.1000/related"},
                                                "instance": {
                                                    "accessright": {"@classid": "OPEN"},
                                                    "webresource": {
                                                        "url": {
                                                            "$": "https://repo.example/related.pdf"
                                                        }
                                                    },
                                                },
                                            },
                                            {
                                                "pid": {"$": "10.1000/target"},
                                                "instance": {
                                                    "accessright": {"@classid": "OPEN"},
                                                    "webresource": {
                                                        "url": {
                                                            "$": "https://repo.example/article/target"
                                                        }
                                                    },
                                                },
                                            },
                                        ]
                                    },
                                }
                            }
                        }
                    }
                ]
            }
        }
    }

    with patch.object(source.session, "get", return_value=_make_json_response(api_data)):
        metadata = source.get_metadata("10.1000/target")

    assert metadata is not None
    assert metadata["pdf_url"] == "https://repo.example/article/target"


def test_openaire_exact_child_metadata_overrides_wrong_parent_metadata():
    source = OpenAireSource(timeout=5)
    api_data = {
        "response": {
            "results": {
                "result": [
                    {
                        "metadata": {
                            "oaf:entity": {
                                "oaf:result": {
                                    "pid": {"$": "10.1000/target"},
                                    "title": {"$": "Wrong parent title"},
                                    "dateofacceptance": {"$": "2010-01-01"},
                                    "children": {
                                        "result": {
                                            "pid": {"$": "10.1000/target"},
                                            "title": {"$": "Exact title"},
                                            "dateofacceptance": {"$": "2024-06-30"},
                                            "instance": {
                                                "accessright": {"@classid": "OPEN"},
                                                "webresource": {
                                                    "url": {"$": "https://repo.example/exact.pdf"}
                                                },
                                            },
                                        }
                                    },
                                }
                            }
                        }
                    }
                ]
            }
        }
    }

    with patch.object(source.session, "get", return_value=_make_json_response(api_data)):
        metadata = source.get_metadata("10.1000/target")

    assert metadata is not None
    assert metadata["pdf_url"] == "https://repo.example/exact.pdf"
    assert metadata["title"] == "Exact title"
    assert metadata["year"] == 2024
