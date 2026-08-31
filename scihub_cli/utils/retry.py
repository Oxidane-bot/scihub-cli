"""
Retry mechanism utilities for Sci-Hub CLI.
"""

import math
import time
from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
from functools import wraps
from typing import Any

from ..utils.logging import get_logger

logger = get_logger(__name__)

# A server can legitimately ask a client to wait longer than the normal
# exponential backoff, but an unbounded Retry-After must not turn a CLI call
# into an accidental multi-year sleep.  Callers can raise this budget for a
# known workflow; the default keeps ordinary retries bounded and predictable.
DEFAULT_MAX_RETRY_AFTER_SECONDS = 300.0


# Exception types for classification
class RetryableError(Exception):
    """Exception that should trigger a retry.

    ``retry_after`` is an optional server-provided lower bound (in seconds)
    for the next attempt.  It is deliberately kept on the exception instead
    of encoded in the message so callers can preserve the HTTP response
    semantics without making every retrying operation parse log text.
    """

    def __init__(self, message: str = "", *, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class PermanentError(Exception):
    """Exception that should NOT trigger a retry (permanent failure)."""

    pass


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 2.0,
        backoff_multiplier: float = 2.0,
        max_delay: float = 60.0,
        max_retry_after: float | None = DEFAULT_MAX_RETRY_AFTER_SECONDS,
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.backoff_multiplier = backoff_multiplier
        self.max_delay = max_delay
        # This is a safety budget for provider hints, separate from the
        # exponential backoff cap.  ``None`` retains the safe default rather
        # than permitting an unbounded sleep.
        self.max_retry_after = max_retry_after


class DownloadRetryConfig(RetryConfig):
    """Specialized config for HTTP download retries."""

    def __init__(self):
        super().__init__(max_attempts=3, base_delay=2.0, backoff_multiplier=2.0, max_delay=30.0)


class APIRetryConfig(RetryConfig):
    """Specialized config for API call retries."""

    def __init__(self):
        super().__init__(max_attempts=2, base_delay=1.0, backoff_multiplier=2.0, max_delay=10.0)


def parse_retry_after(value: Any, *, now: float | None = None) -> float | None:
    """Parse an HTTP ``Retry-After`` value into a non-negative delay.

    RFC 9110 permits either a delay-seconds value or an HTTP-date.  Providers
    occasionally emit decimal seconds, so those are accepted as a harmless
    interoperability extension.  Invalid values are ignored by returning
    ``None`` and callers can use their normal exponential backoff.
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None

    try:
        delay = float(text)
    except OverflowError:
        # A syntactically numeric value can exceed float's range.  Preserve
        # the fact that this is an over-budget positive hint so retry callers
        # stop instead of silently falling back to an early retry.
        try:
            numeric_value = Decimal(text)
        except InvalidOperation:
            return None
        if not numeric_value.is_finite():
            return None
        return math.inf if numeric_value > 0 else 0.0
    except (TypeError, ValueError):
        try:
            retry_at = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at is None:
            return None
        if retry_at.tzinfo is None:
            # HTTP-date is defined in GMT; treat a missing timezone as UTC.
            from datetime import timezone

            retry_at = retry_at.replace(tzinfo=timezone.utc)
        timestamp = time.time() if now is None else now
        try:
            delay = retry_at.timestamp() - timestamp
        except (OverflowError, OSError, ValueError):
            # Extremely distant dates can overflow platform timestamp
            # conversion.  Treat them as an unusable hint; retry policy will
            # fall back to its bounded exponential delay.
            return None

    if not math.isfinite(delay):
        # ``float('1e309')`` returns +inf instead of raising.  Distinguish
        # that numeric overflow from explicit non-numeric infinity so callers
        # can stop safely rather than retrying before the advertised delay.
        try:
            numeric_value = Decimal(text)
        except InvalidOperation:
            return None
        if numeric_value.is_finite() and numeric_value > 0:
            return math.inf
        return None
    return max(0.0, delay)


def _retry_delay(
    retry_config: RetryConfig, attempt: int, error: BaseException | None
) -> float | None:
    """Return the next retry delay, honoring a bounded server hint.

    ``None`` means that the operation must stop instead of retrying.  This is
    intentionally different from capping the delay: a cap would retry before
    the provider's explicit lower bound and violate ``Retry-After``.
    """

    exponential = min(
        retry_config.base_delay * (retry_config.backoff_multiplier**attempt),
        retry_config.max_delay,
    )
    retry_after = getattr(error, "retry_after", None)
    if retry_after is None:
        return exponential
    try:
        retry_after_value = float(retry_after)
    except OverflowError:
        # A huge integer/Decimal is an explicit, but unrepresentable, server
        # hint.  Stop rather than retrying before the provider's deadline.
        return None
    except (TypeError, ValueError):
        return exponential
    if not math.isfinite(retry_after_value):
        # An explicit non-finite hint cannot be honored safely.  Do not turn
        # it into an early retry or pass infinity to time.sleep().
        return None
    if retry_after_value < 0:
        # ``parse_retry_after`` already normalizes dates in the past, but
        # callers may construct RetryableError directly.  Negative values are
        # invalid hints, so use the normal bounded backoff.
        return exponential

    configured_budget = getattr(retry_config, "max_retry_after", DEFAULT_MAX_RETRY_AFTER_SECONDS)
    try:
        budget = float(configured_budget)
    except (TypeError, ValueError, OverflowError):
        budget = DEFAULT_MAX_RETRY_AFTER_SECONDS
    if not math.isfinite(budget) or budget < 0:
        budget = DEFAULT_MAX_RETRY_AFTER_SECONDS
    if retry_after_value > budget:
        logger.warning(
            "Retry-After %.1fs exceeds the %.1fs retry budget; stopping retries",
            retry_after_value,
            budget,
        )
        return None

    # A Retry-After value is a lower bound.  Never retry sooner than the
    # provider requested, even when the configured exponential delay is small.
    return max(exponential, retry_after_value, 0.0)


def with_retry(
    retry_config: RetryConfig, exceptions: tuple = (Exception,), logger_name: str | None = None
):
    """Decorator for adding retry logic to functions."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            retry_logger = get_logger(logger_name) if logger_name else logger

            for attempt in range(retry_config.max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < retry_config.max_attempts - 1:
                        # Calculate delay with exponential backoff
                        delay = _retry_delay(retry_config, attempt, e)
                        if delay is None:
                            retry_logger.warning(
                                "Retry-After is outside the safe retry budget; stopping retries"
                            )
                            break
                        retry_logger.warning(
                            f"Attempt {attempt + 1}/{retry_config.max_attempts} failed: {e}. "
                            f"Retrying in {delay:.1f} seconds..."
                        )
                        time.sleep(delay)
                    else:
                        retry_logger.error(
                            f"All {retry_config.max_attempts} attempts failed. Last error: {e}"
                        )

            raise last_exception

        return wrapper

    return decorator


def retry_operation(
    operation: Callable,
    retry_config: RetryConfig,
    operation_name: str = "operation",
    *args,
    **kwargs,
) -> Any:
    """Retry an operation with the given configuration."""
    last_exception = None

    for attempt in range(retry_config.max_attempts):
        try:
            return operation(*args, **kwargs)
        except Exception as e:
            last_exception = e
            if attempt < retry_config.max_attempts - 1:
                delay = _retry_delay(retry_config, attempt, e)
                if delay is None:
                    logger.warning(
                        "%s returned an unsafe Retry-After hint; stopping retries", operation_name
                    )
                    break
                logger.info(
                    f"{operation_name} failed (attempt {attempt + 1}), retrying in {delay:.1f}s..."
                )
                time.sleep(delay)

    logger.error(f"{operation_name} failed after {retry_config.max_attempts} attempts")
    raise last_exception


def retry_with_classification(
    operation: Callable, retry_config: RetryConfig, operation_name: str = "operation"
) -> Any:
    """
    Retry an operation that classifies exceptions.

    Only retries RetryableError. Immediately raises PermanentError.
    """
    last_exception = None

    for attempt in range(retry_config.max_attempts):
        try:
            return operation()
        except PermanentError:
            # Don't retry permanent failures
            raise
        except RetryableError as e:
            last_exception = e
            if attempt < retry_config.max_attempts - 1:
                delay = _retry_delay(retry_config, attempt, e)
                if delay is None:
                    logger.warning(
                        "%s returned an unsafe Retry-After hint; stopping retries", operation_name
                    )
                    break
                logger.info(
                    f"{operation_name} failed (attempt {attempt + 1}), retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
        except Exception as e:
            # Unknown exceptions are considered retryable (conservative)
            last_exception = e
            if attempt < retry_config.max_attempts - 1:
                delay = min(
                    retry_config.base_delay * (retry_config.backoff_multiplier**attempt),
                    retry_config.max_delay,
                )
                logger.warning(
                    f"{operation_name} failed with unknown error (attempt {attempt + 1}), retrying in {delay:.1f}s..."
                )
                time.sleep(delay)

    logger.error(f"{operation_name} failed after {retry_config.max_attempts} attempts")
    raise last_exception


def classify_http_error(status_code: int) -> bool:
    """
    Determine if HTTP error is retryable.

    Returns:
        True if retryable, False if permanent
    """
    # Retryable: 408 (timeout), 425 (too early), 429 (rate limit),
    # 5xx (server errors).  Other 4xx responses remain permanent.
    # Not retryable: 404 (not found), 403 (forbidden), other 4xx
    return status_code in (408, 425, 429) or 500 <= status_code < 600
