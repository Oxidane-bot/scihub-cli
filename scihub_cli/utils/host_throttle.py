"""Small process-wide schedulers for polite per-host HTTP request starts."""

from __future__ import annotations

import math
import threading
import time
from urllib.parse import urlparse

from .retry import DEFAULT_MAX_RETRY_AFTER_SECONDS


class HostThrottle:
    """Serialize request starts per host and honor provider cooldowns.

    A batch can create one source/downloader object per worker, so an
    instance-local delay does not protect a provider when requests run in
    parallel.  This scheduler is intentionally conservative: it only delays
    our own requests and never changes hosts, fingerprints, or access paths.

    Source/API callers use the default interval.  The download path can ask
    for a provider-specific interval via :meth:`download_interval_for`; this
    keeps high-volume PDF streams from immediately following API/page bursts
    on services that are known to rate-limit them.
    """

    _lock = threading.Lock()
    _next_request_at: dict[str, float] = {}
    _minimum_interval_seconds = 0.25
    _download_minimum_interval_seconds = 0.75
    _download_throttled_host_markers = (
        "europepmc.org",
        "ebi.ac.uk",
        "biorxiv.org",
    )

    @classmethod
    def wait_for_slot(cls, url: str, *, interval_seconds: float | None = None) -> None:
        """Wait until the URL's host is allowed to receive another request.

        ``interval_seconds`` is an optional lower bound between starts for
        this request kind.  Keeping the reservation in the shared lock means
        concurrent workers cannot all observe the same slot.  A waiter does
        not reserve a future slot before sleeping: a provider can call
        :meth:`defer` while it sleeps, so the cooldown must be re-checked
        before the waiter is allowed to start.
        """

        host = cls.host_for(url)
        if not host:
            return

        interval = cls._coerce_interval(
            interval_seconds,
            default=cls._minimum_interval_seconds,
        )
        while True:
            with cls._lock:
                now = time.monotonic()
                scheduled = cls._next_request_at.get(host, now)
                delay = max(0.0, scheduled - now)
                if delay <= 0:
                    # Reserve only after observing a currently available
                    # slot.  Another waiter that wins this lock will move
                    # the next slot forward and make us loop after sleeping.
                    cls._next_request_at[host] = now + interval
                    return

            # Do not hold the scheduler lock while sleeping.  This leaves
            # defer() free to extend the cooldown; the next loop iteration
            # then observes that newer deadline instead of proceeding on the
            # stale reservation calculated above.
            time.sleep(delay)

    @classmethod
    def defer(cls, url: str, delay_seconds: float | None) -> None:
        """Apply a server-requested cooldown to a host."""

        host = cls.host_for(url)
        if not host:
            return
        try:
            delay = float(delay_seconds)
        except (TypeError, ValueError, OverflowError):
            return
        if not math.isfinite(delay) or delay > DEFAULT_MAX_RETRY_AFTER_SECONDS:
            # The retry policy will stop on an over-budget explicit hint.  Do
            # not put an unbounded deadline in the shared scheduler: another
            # worker must never end up in time.sleep(inf) or sleep for years.
            return
        delay = max(0.0, delay)
        with cls._lock:
            cls._next_request_at[host] = max(
                cls._next_request_at.get(host, 0.0),
                time.monotonic() + delay,
            )

    @classmethod
    def download_interval_for(cls, url: str) -> float:
        """Return the request-start interval for a PDF download URL."""

        host = cls.host_for(url)
        if cls._matches_download_throttled_host(host):
            return cls._download_minimum_interval_seconds
        return cls._minimum_interval_seconds

    @classmethod
    def default_rate_limit_delay_for(cls, url: str) -> float:
        """Return a short fallback cooldown when 429 omits Retry-After."""

        if cls._matches_download_throttled_host(cls.host_for(url)):
            return cls._download_minimum_interval_seconds
        return cls._minimum_interval_seconds

    @classmethod
    def default_server_error_delay_for(cls, url: str) -> float:
        """Return a short cooldown after a transient server-side 5xx error."""

        # A 5xx is not proof of rate limiting, so this is deliberately shorter
        # than a provider's explicit Retry-After and leaves retry policy to the
        # existing exponential backoff helper.
        return cls.download_interval_for(url)

    @classmethod
    def reset_for_tests(cls) -> None:
        """Clear scheduler state for deterministic unit tests."""

        with cls._lock:
            cls._next_request_at.clear()

    @staticmethod
    def host_for(url: str) -> str:
        try:
            parsed = urlparse(url)
            return (parsed.hostname or "").lower()
        except ValueError:
            return ""

    @classmethod
    def _matches_download_throttled_host(cls, host: str) -> bool:
        return any(
            host == marker or host.endswith(f".{marker}")
            for marker in cls._download_throttled_host_markers
        )

    @staticmethod
    def _coerce_interval(value: float | None, *, default: float) -> float:
        if value is None:
            return max(0.0, float(default))
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return max(0.0, float(default))
