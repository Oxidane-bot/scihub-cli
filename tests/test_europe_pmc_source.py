from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scihub_cli.sources.europe_pmc_common import EuropePMCHostThrottle
from scihub_cli.sources.europe_pmc_oa_source import EuropePMCOASource
from scihub_cli.sources.europe_pmc_source import EuropePMCSource
from scihub_cli.utils.retry import RetryableError, parse_retry_after


def _response(status_code: int, payload: dict | None = None, *, retry_after: str | None = None):
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"Content-Type": "application/json"}
    if retry_after is not None:
        response.headers["Retry-After"] = retry_after
    response.json.return_value = payload or {}
    return response


@pytest.mark.parametrize("source_class", [EuropePMCSource, EuropePMCOASource])
def test_europe_pmc_honors_retry_after_for_rate_limit(source_class):
    source = source_class(timeout=5)
    source.retry_config.max_attempts = 2
    source.retry_config.base_delay = 0
    source.retry_config.max_delay = 0
    payload = {
        "resultList": {
            "result": [
                {
                    "title": "Example",
                    "pubYear": "2020",
                    "isOpenAccess": "Y",
                    "hasPDF": "Y",
                    "fullTextUrlList": {
                        "fullTextUrl": [
                            {"documentStyle": "pdf", "url": "https://repo.example/paper.pdf"}
                        ]
                    },
                }
            ]
        }
    }
    responses = [_response(429, retry_after="7"), _response(200, payload)]

    def fake_get(*args, **kwargs):  # noqa: ARG001
        return responses.pop(0)

    EuropePMCHostThrottle.reset_for_tests()
    with (
        patch.object(source.session, "get", side_effect=fake_get),
        patch.object(EuropePMCHostThrottle, "wait_for_slot"),
        patch("scihub_cli.utils.retry.time.sleep") as sleep,
    ):
        assert source.get_pdf_url("10.1000/example") == "https://repo.example/paper.pdf"

    assert sleep.call_args.args[0] >= 6.9
    EuropePMCHostThrottle.reset_for_tests()


def test_parse_retry_after_accepts_http_date_and_rejects_invalid_values():
    assert parse_retry_after("4") == 4.0
    assert parse_retry_after("not-a-date") is None
    assert parse_retry_after("Thu, 01 Jan 1970 00:00:00 GMT", now=0) == 0.0


def test_europe_pmc_rate_limit_error_carries_retry_after():
    source = EuropePMCSource(timeout=5)
    source.session = MagicMock()
    source.session.get.return_value = _response(429, retry_after="3")

    EuropePMCHostThrottle.reset_for_tests()
    with (
        patch("scihub_cli.sources.europe_pmc_common.time.sleep"),
        pytest.raises(RetryableError) as exc_info,
    ):
        source._fetch_from_api("10.1000/example")

    assert exc_info.value.retry_after == 3.0
    EuropePMCHostThrottle.reset_for_tests()
