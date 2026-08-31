from __future__ import annotations

import sys
from pathlib import Path

import pytest

import scihub_cli
from scihub_cli.client import SciHubClient
from scihub_cli.core.source_manager import SourceManager
from scihub_cli.scihub_dl_refactored import main
from scihub_cli.sources.arxiv_source import ArxivSource
from scihub_cli.sources.base import PaperSource
from scihub_cli.utils.retry import RetryableError


def _make_fake_pdf_bytes(size: int = 12_000) -> bytes:
    header = b"%PDF-1.4\n"
    trailer = b"\n%%EOF\n"
    return header + b"0" * (size - len(header) - len(trailer)) + trailer


class _ArxivResponse:
    def __init__(self, status_code: int, content: bytes = b""):
        self.status_code = status_code
        self.content = content


class _ArxivSession:
    def __init__(self, responses: list[_ArxivResponse]):
        self.responses = responses
        self.calls = 0

    def get(self, *args, **kwargs):  # noqa: ARG002
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


class _CollisionSource(PaperSource):
    @property
    def name(self) -> str:
        return "Direct PDF"

    def can_handle(self, identifier: str) -> bool:  # noqa: ARG002
        return True

    def get_pdf_url(self, identifier: str) -> str:  # noqa: ARG002
        return "https://example.org/paper.pdf"

    def get_metadata(self, identifier: str) -> dict[str, str]:  # noqa: ARG002
        return {"title": "Collision Title", "year": "2020"}


class _WritingDownloader:
    def download_file(self, url: str, output_path: str, progress_callback=None):  # noqa: ARG002
        Path(output_path).write_bytes(_make_fake_pdf_bytes())
        return True, None


def test_package_and_project_versions_are_aligned():
    project_version = None
    for line in Path(__file__).parents[1].joinpath("pyproject.toml").read_text().splitlines():
        if line.startswith("version = "):
            project_version = line.split('"', 2)[1]
            break

    assert project_version == "0.5.4"
    assert scihub_cli.__version__ == project_version


def test_arxiv_retryable_errors_reach_retry_classifier():
    atom = b"""<?xml version="1.0" encoding="utf-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <entry>
        <title>Example arXiv paper</title>
        <published>2020-01-02T03:04:05Z</published>
      </entry>
    </feed>
    """
    source = ArxivSource(timeout=5)
    source.session = _ArxivSession([_ArxivResponse(429), _ArxivResponse(200, atom)])  # type: ignore[assignment]
    source.retry_config.max_attempts = 2
    source.retry_config.base_delay = 0
    source.retry_config.max_delay = 0

    metadata = source.get_metadata("2001.00001")

    assert metadata == {"title": "Example arXiv paper", "year": 2020, "source": "arXiv"}
    assert source.session.calls == 2  # type: ignore[attr-defined]


def test_arxiv_status_classification_is_preserved():
    source = ArxivSource(timeout=5)
    source.session = _ArxivSession([_ArxivResponse(429)])  # type: ignore[assignment]

    with pytest.raises(RetryableError, match="Rate limited"):
        source._fetch_from_api("2001.00001")


def test_missing_input_file_is_an_error(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    missing = tmp_path / "does-not-exist.txt"
    monkeypatch.setattr(sys, "argv", ["scihub-cli", str(missing)])

    assert main() == 1


def test_filename_collision_gets_unique_path_without_overwriting(
    tmp_path: Path,
):
    output_dir = tmp_path / "downloads"
    output_dir.mkdir()
    existing = output_dir / "[2020] - Collision Title.pdf"
    sentinel = b"keep this existing file"
    existing.write_bytes(sentinel)

    source_manager = SourceManager(
        sources=[_CollisionSource()],
        enable_year_routing=False,
    )
    client = SciHubClient(
        output_dir=str(output_dir),
        timeout=5,
        retries=1,
        downloader=_WritingDownloader(),  # type: ignore[arg-type]
        source_manager=source_manager,
    )

    result = client.download_paper("https://example.org/paper.pdf")

    assert result.success
    assert result.file_path == str(output_dir / "[2020] - Collision Title (1).pdf")
    assert existing.read_bytes() == sentinel
    assert Path(result.file_path).read_bytes()[:4] == b"%PDF"
    assert not list(output_dir.glob("*.scihub-cli.lock"))


def test_download_from_file_propagates_missing_path(tmp_path: Path):
    client = SciHubClient(
        output_dir=str(tmp_path / "downloads"),
        source_manager=SourceManager(sources=[], enable_year_routing=False),
    )

    with pytest.raises(FileNotFoundError):
        client.download_from_file(str(tmp_path / "missing.txt"))


def test_collision_reservations_are_atomic_and_released(tmp_path: Path):
    from scihub_cli.core.file_manager import FileManager

    manager = FileManager(str(tmp_path))
    first = manager.reserve_output_path("paper.pdf")
    second = manager.reserve_output_path("paper.pdf")

    assert Path(first).name == "paper.pdf"
    assert Path(second).name == "paper (1).pdf"

    manager.release_output_path(first, remove_file=True)
    manager.release_output_path(second, remove_file=True)
    assert not list(tmp_path.glob("*.scihub-cli.lock"))
