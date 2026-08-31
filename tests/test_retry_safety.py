from __future__ import annotations

import math
from unittest.mock import patch

import pytest

from scihub_cli.utils.retry import (
    RetryableError,
    RetryConfig,
    parse_retry_after,
    retry_with_classification,
)


def test_retry_after_is_honored_when_within_budget():
    config = RetryConfig(
        max_attempts=2,
        base_delay=0.0,
        max_delay=0.0,
        max_retry_after=7.0,
    )
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RetryableError("HTTP 429", retry_after=7.0)
        return "ok"

    with patch("scihub_cli.utils.retry.time.sleep") as sleep:
        assert retry_with_classification(operation, config) == "ok"

    assert calls == 2
    sleep.assert_called_once_with(7.0)


def test_oversized_retry_after_stops_without_sleeping_or_retrying():
    config = RetryConfig(
        max_attempts=3,
        base_delay=0.0,
        max_delay=0.0,
        max_retry_after=30.0,
    )
    calls = 0
    huge_hint = 10**1000

    def operation():
        nonlocal calls
        calls += 1
        raise RetryableError("HTTP 429", retry_after=huge_hint)

    with (
        patch("scihub_cli.utils.retry.time.sleep") as sleep,
        pytest.raises(RetryableError, match="HTTP 429"),
    ):
        retry_with_classification(operation, config)

    assert calls == 1
    sleep.assert_not_called()


@pytest.mark.parametrize("hint", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_retry_after_stops_without_sleeping_or_retrying(hint: float):
    config = RetryConfig(max_attempts=2, base_delay=0.0, max_delay=0.0)
    calls = 0

    def operation():
        nonlocal calls
        calls += 1
        raise RetryableError("HTTP 429", retry_after=hint)

    with (
        patch("scihub_cli.utils.retry.time.sleep") as sleep,
        pytest.raises(RetryableError, match="HTTP 429"),
    ):
        retry_with_classification(operation, config)

    assert calls == 1
    sleep.assert_not_called()


def test_parse_retry_after_rejects_nonfinite_value():
    # Numeric overflow is retained as an explicit sentinel so retry callers
    # can stop rather than silently retrying before the provider's deadline.
    assert math.isinf(parse_retry_after("1e309"))
    assert parse_retry_after("inf") is None
