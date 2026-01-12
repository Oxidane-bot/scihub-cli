#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import tempfile
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from scihub_cli.config.mirrors import MirrorConfig
from scihub_cli.core.doi_processor import DOIProcessor
from scihub_cli.core.downloader import FileDownloader
from scihub_cli.core.parser import ContentParser


@dataclass(frozen=True)
class MirrorProbeResult:
    mirror: str
    ok: bool
    doi: str | None
    page_status: int | None
    page_ms: float | None
    pdf_ms: float | None
    total_ms: float | None
    pdf_bytes: int | None
    pdf_url: str | None
    error: str | None


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        output.append(item)
    return output


def _normalize_dois(raw_dois: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for raw in raw_dois:
        doi = DOIProcessor.normalize_doi(raw)
        if doi.startswith("10."):
            normalized.append(doi)
    return _dedupe(normalized)


def _load_dois(args: argparse.Namespace) -> list[str]:
    raw: list[str] = list(args.doi or [])
    if args.doi_file:
        text = Path(args.doi_file).read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            raw.append(line)
    dois = _normalize_dois(raw)
    if not dois:
        raise SystemExit("No valid DOIs provided. Use --doi or --doi-file.")
    return dois


def _build_scihub_urls(mirror: str, doi: str) -> list[str]:
    formatted = DOIProcessor.format_doi_for_url(doi)
    urls = [f"{mirror}/{formatted}"]
    fallback = f"{mirror}/{doi}"
    if fallback != urls[0]:
        urls.append(fallback)
    return urls


def _safe_output_path(output_dir: Path, mirror: str, doi: str) -> Path:
    host = urlparse(mirror).netloc.replace(":", "_")
    safe_doi = doi.replace("/", "_")
    return output_dir / f"{host}__{safe_doi}.pdf"


def _probe_mirror(
    mirror: str,
    dois: list[str],
    timeout: int,
    mode: str,
    output_dir: Path | None,
) -> MirrorProbeResult:
    downloader = FileDownloader(timeout=timeout)
    downloader.retry_config.max_attempts = 1
    downloader.retry_config.base_delay = 0.0
    downloader.retry_config.max_delay = 0.0
    parser = ContentParser()

    last_error = None
    last_status = None
    last_page_ms = None

    for doi in dois:
        page_ms = 0.0
        status = None
        pdf_url = None
        for url in _build_scihub_urls(mirror, doi):
            start = time.monotonic()
            html, status = downloader.get_page_content(url)
            page_ms += (time.monotonic() - start) * 1000
            if not html or status != 200:
                continue
            candidate = parser.extract_download_url(html, mirror)
            if candidate:
                pdf_url = candidate
                break

        last_status = status
        last_page_ms = page_ms

        if status != 200:
            last_error = f"page {status}"
            continue

        if not pdf_url:
            last_error = "no pdf url"
            continue

        start = time.monotonic()
        pdf_bytes = None
        if mode == "probe":
            pdf_ok = downloader.probe_pdf_url(pdf_url)
            pdf_ms = (time.monotonic() - start) * 1000
            if pdf_ok:
                total_ms = page_ms + pdf_ms
                return MirrorProbeResult(
                    mirror=mirror,
                    ok=True,
                    doi=doi,
                    page_status=status,
                    page_ms=page_ms,
                    pdf_ms=pdf_ms,
                    total_ms=total_ms,
                    pdf_bytes=None,
                    pdf_url=pdf_url,
                    error=None,
                )
            last_error = "pdf probe failed"
            continue

        download_path = None
        try:
            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                download_path = _safe_output_path(output_dir, mirror, doi)
            else:
                handle, temp_path = tempfile.mkstemp(suffix=".pdf")
                os.close(handle)
                download_path = Path(temp_path)

            success, error = downloader.download_file(str(pdf_url), str(download_path))
            pdf_ms = (time.monotonic() - start) * 1000
            if success:
                pdf_bytes = download_path.stat().st_size
                total_ms = page_ms + pdf_ms
                return MirrorProbeResult(
                    mirror=mirror,
                    ok=True,
                    doi=doi,
                    page_status=status,
                    page_ms=page_ms,
                    pdf_ms=pdf_ms,
                    total_ms=total_ms,
                    pdf_bytes=pdf_bytes,
                    pdf_url=pdf_url,
                    error=None,
                )
            last_error = error or "download failed"
        finally:
            if output_dir is None and download_path is not None and download_path.exists():
                download_path.unlink()

    return MirrorProbeResult(
        mirror=mirror,
        ok=False,
        doi=None,
        page_status=last_status,
        page_ms=last_page_ms,
        pdf_ms=None,
        total_ms=None,
        pdf_bytes=None,
        pdf_url=None,
        error=last_error,
    )


def _format_ms(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.0f}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Probe Sci-Hub mirrors by fetching a DOI and checking PDF availability."
    )
    parser.add_argument("--doi", action="append", help="DOI to probe (repeatable)")
    parser.add_argument("--doi-file", help="File with DOIs (one per line, # for comments)")
    parser.add_argument(
        "--timeout", type=int, default=15, help="Timeout per request in seconds (default: 15)"
    )
    parser.add_argument(
        "--mode",
        choices=("download", "probe"),
        default="download",
        help="download: fetch full PDF; probe: fetch only PDF header (default: download)",
    )
    parser.add_argument(
        "--output-dir",
        help="Directory to keep successful PDFs (default: temp files deleted)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=4,
        help="Max parallel mirror probes (default: 4)",
    )
    args = parser.parse_args()

    dois = _load_dois(args)
    mirrors = MirrorConfig.get_all_mirrors()
    output_dir = Path(args.output_dir) if args.output_dir else None

    results: list[MirrorProbeResult] = []
    with ThreadPoolExecutor(max_workers=min(args.max_workers, len(mirrors))) as executor:
        futures = {
            executor.submit(
                _probe_mirror, mirror, dois, args.timeout, args.mode, output_dir
            ): mirror
            for mirror in mirrors
        }
        for future in as_completed(futures):
            results.append(future.result())

    mirror_order = {mirror: idx for idx, mirror in enumerate(mirrors)}
    results.sort(key=lambda item: mirror_order.get(item.mirror, 0))

    print(f"mode={args.mode} timeout={args.timeout}s mirrors={len(mirrors)} dois={len(dois)}")
    print("mirror\tok\tdoi\tstatus\tpage_ms\tpdf_ms\ttotal_ms\tpdf_bytes")
    for result in results:
        print(
            f"{result.mirror}\t"
            f"{'yes' if result.ok else 'no'}\t"
            f"{result.doi or '-'}\t"
            f"{result.page_status or '-'}\t"
            f"{_format_ms(result.page_ms)}\t"
            f"{_format_ms(result.pdf_ms)}\t"
            f"{_format_ms(result.total_ms)}\t"
            f"{result.pdf_bytes or '-'}"
        )

    working = [r for r in results if r.ok and r.total_ms is not None]
    working.sort(key=lambda r: r.total_ms or 0)
    if working:
        print("\nSuggested mirror order (fastest successful first):")
        for result in working:
            print(f"- {result.mirror} ({result.total_ms:.0f} ms)")
    else:
        print("\nNo mirrors succeeded with the provided DOIs.")
        for result in results:
            if result.error:
                print(f"- {result.mirror}: {result.error}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
