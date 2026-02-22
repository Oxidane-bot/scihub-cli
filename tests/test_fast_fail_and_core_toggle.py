from pathlib import Path

import requests

from scihub_cli.client import SciHubClient
from scihub_cli.core.downloader import FileDownloader


class _HtmlResponse:
    def __init__(self):
        self.status_code = 200
        self.text = "<html>challenge</html>"
        self.headers = {"Content-Type": "text/html; charset=UTF-8"}

    def iter_content(self, chunk_size=8192):  # noqa: ARG002
        yield b"<html>challenge</html>"


class _HtmlSession:
    def get(self, url: str, **kwargs):  # noqa: ARG002
        return _HtmlResponse()


class _ForbiddenResponse:
    status_code = 403
    text = "Forbidden"
    headers = {"Content-Type": "text/html"}


class _ForbiddenSession:
    def get(self, url: str, **kwargs):  # noqa: ARG002
        return _ForbiddenResponse()


class _SlowPdfResponse:
    def __init__(self, sleep_seconds: float = 0.03):
        self.status_code = 200
        self.text = ""
        self.headers = {"Content-Type": "application/pdf"}
        self._sleep_seconds = sleep_seconds

    def iter_content(self, chunk_size=8192):  # noqa: ARG002
        import time

        yield b"%PDF"
        time.sleep(self._sleep_seconds)
        while True:
            yield b"0" * 1024
            time.sleep(self._sleep_seconds)


class _SlowPdfSession:
    def get(self, url: str, **kwargs):  # noqa: ARG002
        return _SlowPdfResponse()


class _FiniteSlowPdfResponse:
    def __init__(self, sleep_seconds: float = 0.02, chunks: int = 5):
        self.status_code = 200
        self.text = ""
        self.headers = {"Content-Type": "application/pdf"}
        self._sleep_seconds = sleep_seconds
        self._chunks = chunks

    def iter_content(self, chunk_size=8192):  # noqa: ARG002
        import time

        yield b"%PDF"
        for _ in range(self._chunks):
            time.sleep(self._sleep_seconds)
            yield b"0" * 1024


class _FiniteSlowPdfSession:
    def get(self, url: str, **kwargs):  # noqa: ARG002
        return _FiniteSlowPdfResponse()


class _TimeoutSession:
    def get(self, url: str, **kwargs):  # noqa: ARG002
        raise requests.Timeout("timeout")


class _CountingSession:
    def __init__(self):
        self.calls = 0

    def get(self, url: str, **kwargs):  # noqa: ARG002
        self.calls += 1
        return _ForbiddenResponse()


def test_disable_core_removes_core_source(tmp_path: Path):
    client = SciHubClient(
        output_dir=str(tmp_path / "out-disabled"),
        timeout=5,
        retries=1,
        enable_core=False,
    )
    assert "CORE" not in client.source_manager.sources

    client_with_core = SciHubClient(
        output_dir=str(tmp_path / "out-enabled"),
        timeout=5,
        retries=1,
        enable_core=True,
    )
    assert "CORE" in client_with_core.source_manager.sources


def test_fast_fail_skips_bypass_and_recovery(tmp_path: Path):
    downloader = FileDownloader(session=_HtmlSession(), timeout=5, fast_fail=True)  # type: ignore[arg-type]

    def _unexpected_bypass(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("Bypass should not run in fast-fail mode")

    downloader._download_with_cloudscraper = _unexpected_bypass  # type: ignore[method-assign]
    downloader._download_with_curl_cffi = _unexpected_bypass  # type: ignore[method-assign]

    output = tmp_path / "fast-fail.pdf"
    success, error = downloader.download_file("https://example.org/paper.pdf", str(output))

    assert not success
    assert error is not None
    assert "Server returned HTML instead of PDF" in error
    assert not output.exists()


def test_fast_fail_uses_single_download_attempt():
    downloader = FileDownloader(session=_HtmlSession(), timeout=5, fast_fail=True)  # type: ignore[arg-type]
    assert downloader.retry_config.max_attempts == 1


def test_fast_fail_skips_page_403_bypass():
    downloader = FileDownloader(session=_ForbiddenSession(), timeout=5, fast_fail=True)  # type: ignore[arg-type]

    def _unexpected(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("Bypass should not run in fast-fail page fetch")

    downloader._get_page_with_cloudscraper = _unexpected  # type: ignore[method-assign]
    downloader._get_page_with_curl_cffi = _unexpected  # type: ignore[method-assign]

    html, status = downloader.get_page_content("https://example.org/article")
    assert status == 403
    assert html == "Forbidden"


def test_download_deadline_interrupts_slow_stream(tmp_path: Path):
    downloader = FileDownloader(
        session=_SlowPdfSession(),
        timeout=5,
        fast_fail=True,
        retries=1,
        download_deadline_seconds=0.08,
    )  # type: ignore[arg-type]
    output = tmp_path / "slow.pdf"
    success, error = downloader.download_file("https://example.org/slow.pdf", str(output))

    assert not success
    assert error is not None
    assert "Download deadline exceeded" in error
    assert not output.exists()


def test_fast_fail_deadline_grace_allows_active_pdf_to_finish(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(FileDownloader, "_FAST_FAIL_DEADLINE_MIN_SECONDS_FOR_GRACE", 0.05)
    monkeypatch.setattr(FileDownloader, "_FAST_FAIL_DEADLINE_PROGRESS_MIN_BYTES", 4)
    monkeypatch.setattr(FileDownloader, "_FAST_FAIL_DEADLINE_PROGRESS_GRACE_SECONDS", 0.08)
    monkeypatch.setattr(FileDownloader, "_FAST_FAIL_DEADLINE_MAX_EXTENSIONS", 1)

    downloader = FileDownloader(
        session=_FiniteSlowPdfSession(),
        timeout=5,
        fast_fail=True,
        retries=1,
        download_deadline_seconds=0.05,
    )  # type: ignore[arg-type]
    output = tmp_path / "slow-finite.pdf"

    success, error = downloader.download_file("https://example.edu/paper.pdf", str(output))

    assert success
    assert error is None
    assert output.exists()
    assert output.read_bytes()[:4] == b"%PDF"


def test_fast_fail_mdpi_permanent_failure_uses_lightweight_bypass(tmp_path: Path):
    downloader = FileDownloader(session=_HtmlSession(), timeout=5, fast_fail=True)  # type: ignore[arg-type]

    def _curl_success(url: str, output_path: str, progress_callback=None):  # noqa: ARG001
        Path(output_path).write_bytes(b"%PDF-1.4\\n%%EOF\\n")
        if progress_callback:
            progress_callback(14, 14)
        return True, None

    downloader._download_with_cloudscraper = lambda *a, **k: (_ for _ in ()).throw(  # type: ignore[method-assign]
        AssertionError("cloudscraper should stay disabled in fast-fail")
    )
    downloader._download_with_curl_cffi = _curl_success  # type: ignore[method-assign]

    output = tmp_path / "mdpi-success.pdf"
    success, error = downloader.download_file(
        "https://www.mdpi.com/2072-666X/13/6/944/pdf", str(output)
    )

    assert success
    assert error is None
    assert output.exists()
    assert output.read_bytes()[:4] == b"%PDF"


def test_fast_fail_mdpi_timeout_uses_lightweight_bypass(tmp_path: Path):
    downloader = FileDownloader(session=_TimeoutSession(), timeout=5, fast_fail=True)  # type: ignore[arg-type]

    def _curl_success(url: str, output_path: str, progress_callback=None):  # noqa: ARG001
        Path(output_path).write_bytes(b"%PDF-1.4\\n%%EOF\\n")
        return True, None

    downloader._download_with_curl_cffi = _curl_success  # type: ignore[method-assign]

    output = tmp_path / "mdpi-timeout-success.pdf"
    success, error = downloader.download_file(
        "https://www.mdpi.com/1996-1073/16/1/519/pdf", str(output)
    )

    assert success
    assert error is None
    assert output.exists()


def test_fast_fail_skips_challenge_heavy_direct_pdf_without_network(tmp_path: Path):
    session = _CountingSession()
    downloader = FileDownloader(session=session, timeout=5, fast_fail=True)  # type: ignore[arg-type]

    output = tmp_path / "sciencedirect.pdf"
    success, error = downloader.download_file(
        "https://www.sciencedirect.com/science/article/pii/S1364032121006948/pdfft",
        str(output),
    )

    assert not success
    assert error == "Skipped challenge-heavy PDF URL in fast-fail mode"
    assert session.calls == 0
    assert not output.exists()


def test_fast_fail_mdpi_lightweight_bypass_retries_on_timeout(tmp_path: Path):
    downloader = FileDownloader(session=_TimeoutSession(), timeout=5, fast_fail=True)  # type: ignore[arg-type]
    calls = {"n": 0}

    def _curl_flaky(url: str, output_path: str, progress_callback=None):  # noqa: ARG001
        calls["n"] += 1
        if calls["n"] == 1:
            return False, "Request timed out"
        Path(output_path).write_bytes(b"%PDF-1.4\\n%%EOF\\n")
        if progress_callback:
            progress_callback(14, 14)
        return True, None

    downloader._download_with_curl_cffi = _curl_flaky  # type: ignore[method-assign]

    output = tmp_path / "mdpi-retry-success.pdf"
    success, error = downloader.download_file(
        "https://www.mdpi.com/1996-1073/16/1/519/pdf", str(output)
    )

    assert success
    assert error is None
    assert output.exists()
    assert calls["n"] == 2


def test_fast_fail_mdpi_lightweight_bypass_does_not_retry_on_403(tmp_path: Path):
    downloader = FileDownloader(session=_TimeoutSession(), timeout=5, fast_fail=True)  # type: ignore[arg-type]
    calls = {"n": 0}

    def _curl_403(url: str, output_path: str, progress_callback=None):  # noqa: ARG001
        calls["n"] += 1
        return False, "HTTP 403"

    downloader._download_with_curl_cffi = _curl_403  # type: ignore[method-assign]

    output = tmp_path / "mdpi-retry-403.pdf"
    success, error = downloader.download_file(
        "https://www.mdpi.com/1996-1073/16/1/519/pdf", str(output)
    )

    assert not success
    assert error == "Download timeout"
    assert calls["n"] == 1
    assert not output.exists()


def test_fast_fail_whitelisted_academic_timeout_uses_lightweight_bypass(tmp_path: Path):
    downloader = FileDownloader(session=_TimeoutSession(), timeout=5, fast_fail=True)  # type: ignore[arg-type]

    def _curl_success(url: str, output_path: str, progress_callback=None):  # noqa: ARG001
        Path(output_path).write_bytes(b"%PDF-1.4\\n%%EOF\\n")
        return True, None

    downloader._download_with_curl_cffi = _curl_success  # type: ignore[method-assign]

    output = tmp_path / "upenn-success.pdf"
    success, error = downloader.download_file(
        "https://seas.upenn.edu/~lior/documents/Analysisandcomparisonofsolar-heatdrivencyclesforspacepowergeneration-published.pdf",
        str(output),
    )

    assert success
    assert error is None
    assert output.exists()


def test_fast_fail_new_whitelisted_timeout_uses_lightweight_bypass(tmp_path: Path):
    downloader = FileDownloader(session=_TimeoutSession(), timeout=5, fast_fail=True)  # type: ignore[arg-type]

    def _curl_success(url: str, output_path: str, progress_callback=None):  # noqa: ARG001
        Path(output_path).write_bytes(b"%PDF-1.4\\n%%EOF\\n")
        return True, None

    downloader._download_with_curl_cffi = _curl_success  # type: ignore[method-assign]

    output = tmp_path / "adb-timeout-success.pdf"
    success, error = downloader.download_file(
        "https://asiacleanenergyforum.adb.org/wp-content/uploads/2018/06/Nicolas-Berneir-Waste-Heat-Recovery-Using-ORC-Turbines.pdf",
        str(output),
    )

    assert success
    assert error is None
    assert output.exists()


def test_fast_fail_non_mdpi_html_does_not_use_lightweight_bypass(tmp_path: Path):
    downloader = FileDownloader(session=_HtmlSession(), timeout=5, fast_fail=True)  # type: ignore[arg-type]
    calls = {"n": 0}

    def _curl_count(url: str, output_path: str, progress_callback=None):  # noqa: ARG001
        calls["n"] += 1
        return False, "Server returned HTML (Content-Type: text/html)"

    downloader._download_with_curl_cffi = _curl_count  # type: ignore[method-assign]

    output = tmp_path / "sage-html.pdf"
    success, error = downloader.download_file(
        "https://methods.sagepub.com/book/mono/example/download.pdf",
        str(output),
    )

    assert not success
    assert error is not None
    assert "Server returned HTML instead of PDF" in error
    assert calls["n"] == 0
    assert not output.exists()
