from __future__ import annotations

import threading
from unittest.mock import call, patch

import pytest

from scihub_cli.core.downloader import FileDownloader
from scihub_cli.sources.europe_pmc_common import EuropePMCHostThrottle
from scihub_cli.utils.host_throttle import HostThrottle


def _make_fake_pdf_bytes() -> bytes:
    return b"%PDF-1.4\nexample\n%%EOF\n"


class _Response:
    def __init__(self, status_code: int, *, retry_after: str | None = None):
        self.status_code = status_code
        self.headers = {
            "Content-Type": "application/pdf" if status_code == 200 else "text/plain",
            "Content-Length": str(len(_make_fake_pdf_bytes())) if status_code == 200 else "0",
        }
        if retry_after is not None:
            self.headers["Retry-After"] = retry_after
        self._content = _make_fake_pdf_bytes() if status_code == 200 else b""
        self.text = ""

    def iter_content(self, chunk_size: int = 8192):  # noqa: ARG002
        if self._content:
            yield self._content

    def close(self):
        return None


class _Session:
    def __init__(self, responses: list[_Response]):
        self.responses = responses
        self.calls = 0

    def get(self, url: str, **kwargs):  # noqa: ARG002
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return response


def test_europe_pmc_name_aliases_shared_download_scheduler():
    assert EuropePMCHostThrottle is HostThrottle


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC1", 0.75),
        ("https://www.ebi.ac.uk/europepmc/rest/search", 0.75),
        ("https://www.biorxiv.org/content/10.1101/examplev1.full.pdf", 0.75),
        ("https://repository.example.org/paper.pdf", 0.25),
    ],
)
def test_download_interval_is_provider_aware(url: str, expected: float):
    assert HostThrottle.download_interval_for(url) == expected


def test_wait_for_slot_reserves_one_slot_per_host(monkeypatch):
    HostThrottle.reset_for_tests()


def test_over_budget_defer_does_not_schedule_an_unbounded_sleep(monkeypatch):
    HostThrottle.reset_for_tests()
    now = [100.0]
    sleeps: list[float] = []

    monkeypatch.setattr("scihub_cli.utils.host_throttle.time.monotonic", lambda: now[0])
    monkeypatch.setattr(
        "scihub_cli.utils.host_throttle.time.sleep", lambda delay: sleeps.append(delay)
    )

    HostThrottle.defer("https://europepmc.org/a.pdf", 10**300)
    HostThrottle.wait_for_slot("https://europepmc.org/a.pdf", interval_seconds=0.75)

    assert sleeps == []
    assert HostThrottle._next_request_at["europepmc.org"] == pytest.approx(100.75)
    HostThrottle.reset_for_tests()
    now = [100.0]
    sleeps: list[float] = []

    monkeypatch.setattr("scihub_cli.utils.host_throttle.time.monotonic", lambda: now[0])

    def _sleep(delay: float) -> None:
        sleeps.append(delay)
        now[0] += delay

    monkeypatch.setattr("scihub_cli.utils.host_throttle.time.sleep", _sleep)

    HostThrottle.wait_for_slot("https://europepmc.org/a.pdf", interval_seconds=0.75)
    HostThrottle.wait_for_slot("https://europepmc.org/b.pdf", interval_seconds=0.75)
    HostThrottle.wait_for_slot("https://other.example.org/c.pdf", interval_seconds=0.25)

    assert sleeps == [pytest.approx(0.75)]
    HostThrottle.reset_for_tests()


def test_waiter_rechecks_cooldown_deferred_during_sleep(monkeypatch):
    """A Retry-After received during a wait invalidates the old slot."""
    HostThrottle.reset_for_tests()
    now = [100.0]
    sleeps: list[float] = []
    url = "https://europepmc.org/a.pdf"

    monkeypatch.setattr("scihub_cli.utils.host_throttle.time.monotonic", lambda: now[0])

    def _sleep(delay: float) -> None:
        sleeps.append(delay)
        now[0] += delay
        if len(sleeps) == 1:
            HostThrottle.defer(url, 5.0)

    monkeypatch.setattr("scihub_cli.utils.host_throttle.time.sleep", _sleep)

    HostThrottle.wait_for_slot(url, interval_seconds=0.75)
    HostThrottle.wait_for_slot(url, interval_seconds=0.75)

    assert sleeps == [pytest.approx(0.75), pytest.approx(5.0)]
    assert HostThrottle._next_request_at["europepmc.org"] == pytest.approx(106.5)
    HostThrottle.reset_for_tests()


def test_concurrent_defer_during_wait_is_observed(monkeypatch):
    """A defer from another worker cannot be bypassed by a sleeping waiter."""
    HostThrottle.reset_for_tests()
    now = [100.0]
    sleeps: list[float] = []
    sleep_started = threading.Event()
    release_sleep = threading.Event()
    url = "https://europepmc.org/a.pdf"

    monkeypatch.setattr("scihub_cli.utils.host_throttle.time.monotonic", lambda: now[0])

    def _sleep(delay: float) -> None:
        sleeps.append(delay)
        if len(sleeps) == 1:
            sleep_started.set()
            assert release_sleep.wait(timeout=1.0)
        now[0] += delay

    monkeypatch.setattr("scihub_cli.utils.host_throttle.time.sleep", _sleep)

    HostThrottle.wait_for_slot(url, interval_seconds=0.75)

    waiter = threading.Thread(
        target=HostThrottle.wait_for_slot, args=(url,), kwargs={"interval_seconds": 0.75}
    )
    waiter.start()
    assert sleep_started.wait(timeout=1.0)
    HostThrottle.defer(url, 5.0)
    release_sleep.set()
    waiter.join(timeout=1.0)

    assert not waiter.is_alive()
    assert sleeps == [pytest.approx(0.75), pytest.approx(4.25)]
    assert HostThrottle._next_request_at["europepmc.org"] == pytest.approx(105.75)
    HostThrottle.reset_for_tests()


@pytest.mark.parametrize(
    ("status_code", "retry_after", "expected_defer"),
    [
        (429, "5", 5.0),
        (520, None, 0.75),
    ],
)
def test_pdf_download_defers_rate_limited_or_server_error_host(
    tmp_path, status_code: int, retry_after: str | None, expected_defer: float
):
    url = "https://europepmc.org/backend/ptpmcrender.fcgi?accid=PMC123&blobtype=pdf"
    session = _Session([_Response(status_code, retry_after=retry_after), _Response(200)])
    downloader = FileDownloader(session=session, timeout=5)  # type: ignore[arg-type]
    downloader.retry_config.max_attempts = 2
    downloader.retry_config.base_delay = 0.0
    downloader.retry_config.max_delay = 0.0
    output = tmp_path / f"{status_code}.pdf"

    with (
        patch.object(HostThrottle, "wait_for_slot") as wait_for_slot,
        patch.object(HostThrottle, "defer") as defer,
        patch("scihub_cli.utils.retry.time.sleep"),
    ):
        success, error = downloader.download_file(url, str(output))

    assert success, error
    assert wait_for_slot.call_args_list == [
        call(url, interval_seconds=0.75),
        call(url, interval_seconds=0.75),
    ]
    assert defer.call_args == call(url, expected_defer)
    assert output.read_bytes().startswith(b"%PDF")


def test_pdf_probe_also_shares_host_cooldown():
    url = "https://www.biorxiv.org/content/10.1101/examplev1.full.pdf"
    session = _Session([_Response(429, retry_after="3")])
    downloader = FileDownloader(session=session, timeout=5)  # type: ignore[arg-type]

    with (
        patch.object(HostThrottle, "wait_for_slot") as wait_for_slot,
        patch.object(HostThrottle, "defer") as defer,
    ):
        assert not downloader.probe_pdf_url(url)

    wait_for_slot.assert_called_once_with(url, interval_seconds=0.75)
    defer.assert_called_once_with(url, 3.0)
