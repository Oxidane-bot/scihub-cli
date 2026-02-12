import json
from pathlib import Path

from scihub_cli.models import DownloadResult
from scihub_cli.scihub_dl_refactored import _write_failure_report


def _build_result(identifier: str, success: bool, **kwargs) -> DownloadResult:
    return DownloadResult(
        identifier=identifier,
        normalized_identifier=kwargs.pop("normalized_identifier", identifier),
        success=success,
        **kwargs,
    )


def test_write_failure_report_skips_when_all_success(tmp_path: Path):
    results = [
        _build_result(
            "10.1/ok",
            True,
            source="arXiv",
            md_success=True,
            file_path=str(tmp_path / "ok.pdf"),
        )
    ]

    report_path = _write_failure_report(results, str(tmp_path))

    assert report_path is None
    assert not (tmp_path / "download-report.json").exists()


def test_write_failure_report_contains_failures(tmp_path: Path):
    results = [
        _build_result(
            "10.1/fail-download",
            False,
            source="Unpaywall",
            error="Access denied (403)",
            source_attempts=[
                {"source": "Unpaywall", "status": "error", "error": "Access denied (403)"}
            ],
            html_snapshots=[
                {
                    "source": "Unpaywall",
                    "status_code": 403,
                    "fetcher": "requests",
                    "file_path": "trace/fail-download-403.html",
                }
            ],
        ),
        _build_result(
            "10.1/fail-md",
            True,
            source="arXiv",
            file_path=str(tmp_path / "fail-md.pdf"),
            md_success=False,
            md_error="conversion failed",
        ),
        _build_result(
            "10.1/success",
            True,
            source="CORE",
            file_path=str(tmp_path / "success.pdf"),
            md_success=True,
        ),
    ]

    report_path = _write_failure_report(results, str(tmp_path))

    assert report_path is not None
    payload = json.loads(Path(report_path).read_text(encoding="utf-8"))
    assert payload["summary"]["total"] == 3
    assert payload["summary"]["download_failures"] == 1
    assert payload["summary"]["md_failures"] == 1
    assert payload["download_failures"][0]["identifier"] == "10.1/fail-download"
    assert payload["download_failures"][0]["source_attempts"]
    assert payload["download_failures"][0]["html_snapshots"]
    assert payload["md_failures"][0]["identifier"] == "10.1/fail-md"
