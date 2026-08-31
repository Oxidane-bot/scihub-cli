"""Backward-compatible Europe PMC name for the shared host throttle."""

from __future__ import annotations

import time  # noqa: F401 - kept for callers/tests that patch this module's clock

from ..utils.host_throttle import HostThrottle

# Keep this public name stable for the existing Europe PMC sources and tests.
# It is an alias (rather than a subclass) so API/page and PDF download callers
# share one process-wide reservation table.
EuropePMCHostThrottle = HostThrottle

__all__ = ["EuropePMCHostThrottle"]
