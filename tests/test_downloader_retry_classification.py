import pytest

from scihub_cli.core.downloader import FileDownloader


def _make_fake_pdf_bytes(size: int = 12000) -> bytes:
    assert size > 4
    header = b"%PDF-1.4\n"
    body = b"0" * (size - len(header) - len(b"\n%%EOF\n"))
    return header + body + b"\n%%EOF\n"


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        content: bytes = b"",
        content_type: str = "application/pdf",
    ):
        self.status_code = status_code
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(content)),
        }
        self._content = content

    def iter_content(self, chunk_size: int = 8192):
        for i in range(0, len(self._content), chunk_size):
            yield self._content[i : i + chunk_size]


class _SequencedSession:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = responses
        self.calls = 0

    def get(self, url: str, timeout=None, stream=False):  # noqa: ARG002
        idx = min(self.calls, len(self._responses) - 1)
        self.calls += 1
        return self._responses[idx]


@pytest.mark.parametrize("status_code", [202, 408, 429])
def test_retryable_http_statuses_are_retried(tmp_path, status_code: int):
    pdf_bytes = _make_fake_pdf_bytes()
    session = _SequencedSession(
        [
            _FakeResponse(status_code=status_code, content=b"", content_type="text/plain"),
            _FakeResponse(status_code=200, content=pdf_bytes, content_type="application/pdf"),
        ]
    )
    downloader = FileDownloader(session=session, timeout=5)  # type: ignore[arg-type]
    downloader.retry_config.max_attempts = 3
    downloader.retry_config.base_delay = 0.0
    downloader.retry_config.max_delay = 0.0

    output = tmp_path / f"{status_code}.pdf"
    success, error = downloader.download_file("https://example.org/paper.pdf", str(output))

    assert success, error
    assert session.calls == 2
    assert output.read_bytes()[:4] == b"%PDF"
