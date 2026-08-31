from __future__ import annotations

from pathlib import Path

from scihub_cli.core.downloader import FileDownloader


class _FiniteOstiPdfResponse:
    status_code = 200
    text = ""
    headers = {"Content-Type": "application/pdf"}

    def iter_content(self, chunk_size=8192):  # noqa: ARG002
        import time

        yield b"%PDF"
        for _ in range(5):
            time.sleep(0.02)
            yield b"0" * 1024


class _OstiSession:
    def get(self, url: str, **kwargs):  # noqa: ARG002
        return _FiniteOstiPdfResponse()


def test_osti_stream_gets_bounded_deadline_grace(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(FileDownloader, "_FAST_FAIL_DEADLINE_MIN_SECONDS_FOR_GRACE", 0.05)
    monkeypatch.setattr(FileDownloader, "_FAST_FAIL_DEADLINE_PROGRESS_MIN_BYTES", 4)
    monkeypatch.setattr(FileDownloader, "_FAST_FAIL_DEADLINE_PROGRESS_GRACE_SECONDS", 0.2)
    monkeypatch.setattr(FileDownloader, "_FAST_FAIL_DEADLINE_MAX_EXTENSIONS", 1)

    downloader = FileDownloader(
        session=_OstiSession(),
        timeout=5,
        fast_fail=False,
        retries=1,
        download_deadline_seconds=0.05,
    )  # type: ignore[arg-type]
    output = tmp_path / "osti.pdf"

    success, error = downloader.download_file(
        "https://www.osti.gov/servlets/purl/1234567", str(output)
    )

    assert success
    assert error is None
    assert output.read_bytes()[:4] == b"%PDF"
