"""
Retry mechanism utilities for Sci-Hub CLI.
"""

import time
from collections.abc import Callable
from functools import wraps
from typing import Any

from ..utils.logging import get_logger

logger = get_logger(__name__)


# Exception types for classification
class RetryableError(Exception):
    """Exception that should trigger a retry."""

    pass


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
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.backoff_multiplier = backoff_multiplier
        self.max_delay = max_delay


class DownloadRetryConfig(RetryConfig):
    """Specialized config for HTTP download retries."""

    def __init__(self):
        super().__init__(max_attempts=3, base_delay=2.0, backoff_multiplier=2.0, max_delay=30.0)


class APIRetryConfig(RetryConfig):
    """Specialized config for API call retries."""

    def __init__(self):
        super().__init__(max_attempts=2, base_delay=1.0, backoff_multiplier=2.0, max_delay=10.0)


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
                        delay = min(
                            retry_config.base_delay * (retry_config.backoff_multiplier**attempt),
                            retry_config.max_delay,
                        )
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
                delay = min(
                    retry_config.base_delay * (retry_config.backoff_multiplier**attempt),
                    retry_config.max_delay,
                )
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
                delay = min(
                    retry_config.base_delay * (retry_config.backoff_multiplier**attempt),
                    retry_config.max_delay,
                )
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
    # Retryable: 408 (timeout), 429 (rate limit), 5xx (server errors)
    # Not retryable: 404 (not found), 403 (forbidden), other 4xx
    return status_code in (408, 429) or status_code >= 500
