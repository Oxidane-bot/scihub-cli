"""Shared data models for download results and progress reporting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class DownloadProgress:
    """Progress update for a single download."""

    identifier: str
    url: str
    bytes_downloaded: int
    total_bytes: int | None
    done: bool = False


ProgressCallback = Callable[[DownloadProgress], None]


@dataclass
class DownloadResult:
    """Result for a single download attempt."""

    identifier: str
    normalized_identifier: str
    success: bool
    file_path: str | None = None
    file_size: int | None = None
    source: str | None = None
    metadata: dict[str, Any] | None = None
    title: str | None = None
    year: int | None = None
    download_url: str | None = None
    download_time: float | None = None
    error: str | None = None
