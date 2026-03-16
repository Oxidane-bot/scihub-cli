#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from scihub_cli.config.auto_tuning import DEFAULT_RULES, load_auto_tuning, save_auto_tuning


def _normalize_host(value: str | None) -> str | None:
    if not value:
        return None
    host = value.strip().lower()
    if host.startswith("www."):
        host = host[4:]
    return host or None


def _host_from_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    return _normalize_host(parsed.netloc)


def _read_html(path: str | None, max_chars: int = 200_000) -> str | None:
    if not path:
        return None
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return None
    if len(text) > max_chars:
        return text[:max_chars]
    return text


def _is_akamai_access_denied(html: str) -> bool:
    lowered = (html or "").lower()
    return (
        "access denied" in lowered
        and "errors.edgesuite.net" in lowered
        and "don't have permission to access" in lowered
    )


def _is_cloudflare_challenge(html: str) -> bool:
    lowered = (html or "").lower()
    return any(
        token in lowered
        for token in (
            "attention required! | cloudflare",
            "cloudflare ray id",
            "/cdn-cgi/challenge-platform/",
            "__cf_chl",
            "just a moment...",
        )
    )


def _is_generic_challenge(html: str) -> bool:
    lowered = (html or "").lower()
    return any(
        token in lowered
        for token in (
            "enable javascript and cookies to continue",
            "verify that you're not a robot",
            "recaptcha/api.js",
            "grecaptcha.render",
            "captcha.awswaf.com",
        )
    )


def _is_paywall_or_login(html: str) -> bool:
    lowered = (html or "").lower()
    return any(
        token in lowered
        for token in (
            "institutional login",
            "institutional access",
            "openathens",
            "shibboleth",
            "subscribe",
            "subscription",
            "purchase this article",
            "buy article",
            "rent this article",
            "get access",
            "paywall",
            "subscribers only",
            "ieee xplore login",
            "currentpage:  'login'",
        )
    )


def _ensure_rules(path: Path) -> dict:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(DEFAULT_RULES, ensure_ascii=False, indent=2), encoding="utf-8")
    return load_auto_tuning()


def _add_unique(target: list[str], items: list[str]) -> list[str]:
    seen = set(target)
    for item in items:
        if item and item not in seen:
            seen.add(item)
            target.append(item)
    return target


def _analyze_report(report_path: Path) -> dict:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    failures = [r for r in data.get("results", []) if not r.get("success")]

    akamai_403 = Counter()
    cf_challenge = Counter()
    generic_challenge = Counter()
    paywall = Counter()
    status_403 = Counter()
    skipped_challenge = Counter()

    for result in failures:
        error = (result.get("error") or "").lower()
        download_url = result.get("download_url")
        if "skipped challenge-heavy pdf url in fast-fail mode" in error:
            host = _host_from_url(download_url)
            if host:
                skipped_challenge[host] += 1

        snapshots = result.get("html_snapshots") or []
        for snap in snapshots:
            url = snap.get("url")
            host = _host_from_url(url)
            if not host:
                continue
            status = snap.get("status_code")
            html = _read_html(snap.get("file_path"))
            if status == 403:
                status_403[host] += 1
            if not html:
                continue
            if _is_akamai_access_denied(html):
                akamai_403[host] += 1
            if _is_cloudflare_challenge(html):
                cf_challenge[host] += 1
            if _is_generic_challenge(html):
                generic_challenge[host] += 1
            if _is_paywall_or_login(html):
                paywall[host] += 1

    return {
        "summary": data.get("summary"),
        "akamai_403": akamai_403,
        "cloudflare_challenge": cf_challenge,
        "generic_challenge": generic_challenge,
        "paywall": paywall,
        "status_403": status_403,
        "skipped_challenge": skipped_challenge,
    }


def _update_rules_from_analysis(rules: dict, analysis: dict) -> dict:
    ua_overrides = rules.setdefault("ua_overrides", {"curl": [], "browser": []})
    ua_overrides.setdefault("curl", [])
    ua_overrides.setdefault("browser", [])

    add_curl = []
    add_lightweight = []
    add_page_bypass = []
    add_skip_challenge = []
    drop_skip_challenge = []

    for host, count in analysis["akamai_403"].items():
        if count >= 3:
            add_curl.append(host)
            add_lightweight.append(host)

    for host, count in analysis["status_403"].items():
        if count >= 5:
            add_lightweight.append(host)

    for host, count in analysis["cloudflare_challenge"].items():
        if count >= 3:
            add_page_bypass.append(host)

    for host, count in analysis["generic_challenge"].items():
        if count >= 5:
            add_page_bypass.append(host)

    for host, count in analysis["paywall"].items():
        if count >= 5:
            add_skip_challenge.append(host)

    for host, count in analysis["skipped_challenge"].items():
        if count >= 3:
            drop_skip_challenge.append(host)

    ua_overrides["curl"] = _add_unique(ua_overrides.get("curl", []), add_curl)
    rules["fast_fail_lightweight_bypass_hosts_add"] = _add_unique(
        rules.get("fast_fail_lightweight_bypass_hosts_add", []),
        add_lightweight,
    )
    rules["fast_fail_page_bypass_hosts_add"] = _add_unique(
        rules.get("fast_fail_page_bypass_hosts_add", []),
        add_page_bypass,
    )
    rules["fast_fail_skip_challenge_download_hosts_add"] = _add_unique(
        rules.get("fast_fail_skip_challenge_download_hosts_add", []),
        add_skip_challenge,
    )
    rules["fast_fail_skip_challenge_download_hosts_drop"] = _add_unique(
        rules.get("fast_fail_skip_challenge_download_hosts_drop", []),
        drop_skip_challenge,
    )

    return rules


def _cleanup_pdfs(output_dir: Path) -> int:
    removed = 0
    for path in output_dir.rglob("*.pdf"):
        try:
            path.unlink()
            removed += 1
        except Exception:
            continue
    return removed


def _next_opt_number(benchmarks_dir: Path, prefix: str) -> int:
    pattern = re.compile(re.escape(prefix) + r"(\\d+)")
    best = 0
    for entry in benchmarks_dir.iterdir():
        if not entry.is_dir():
            continue
        match = pattern.search(entry.name)
        if match:
            best = max(best, int(match.group(1)))
    return best + 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run longrun optimization iterations.")
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--input-file", default="failed_links_578_20260315212513.txt")
    parser.add_argument("--parallel", type=int, default=16)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--benchmarks-dir", default="benchmarks")
    parser.add_argument("--prefix", default="longrun-p16d15-opt")
    parser.add_argument("--rules-path", default="benchmarks/longrun-auto-tuning.json")
    args = parser.parse_args()

    input_file = Path(args.input_file)
    if not input_file.exists():
        raise SystemExit(f"Input file not found: {input_file}")

    benchmarks_dir = Path(args.benchmarks_dir)
    benchmarks_dir.mkdir(parents=True, exist_ok=True)
    rules_path = Path(args.rules_path)

    os.environ["SCIHUB_AUTO_TUNING_PATH"] = str(rules_path)
    rules = _ensure_rules(rules_path)

    start_opt = _next_opt_number(benchmarks_dir, args.prefix)

    for i in range(args.rounds):
        opt_num = start_opt + i
        stamp = time.strftime("%Y%m%d-%H%M%S")
        run_dir = benchmarks_dir / f"{args.prefix}{opt_num:02d}-{stamp}"
        output_dir = run_dir / "output"
        run_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)

        cmd = [
            "uv",
            "run",
            "python",
            "-m",
            "scihub_cli",
            str(input_file),
            "-o",
            str(output_dir),
            "-p",
            str(args.parallel),
            "-t",
            str(args.timeout),
            "--trace-html",
        ]

        log_path = run_dir / "console.log"
        start = time.perf_counter()
        with log_path.open("w", encoding="utf-8") as log:
            log.write(f"Command: {' '.join(cmd)}\n")
            log.write(f"Auto-tuning: {rules_path}\n")
            log.flush()
            subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, check=False)
        elapsed = time.perf_counter() - start
        (run_dir / "time.txt").write_text(f"real {elapsed:.2f}\n", encoding="utf-8")

        report_path = output_dir / "download-report.json"
        analysis = {}
        if report_path.exists():
            analysis = _analyze_report(report_path)
            rules = _update_rules_from_analysis(rules, analysis)
            save_auto_tuning(rules)
            (run_dir / "analysis.json").write_text(
                json.dumps(
                    {
                        "summary": analysis.get("summary"),
                        "akamai_403": analysis.get("akamai_403", {}).most_common(50),
                        "cloudflare_challenge": analysis.get("cloudflare_challenge", {}).most_common(50),
                        "generic_challenge": analysis.get("generic_challenge", {}).most_common(50),
                        "paywall": analysis.get("paywall", {}).most_common(50),
                        "status_403": analysis.get("status_403", {}).most_common(50),
                        "skipped_challenge": analysis.get("skipped_challenge", {}).most_common(50),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            (run_dir / "auto_tuning.json").write_text(
                json.dumps(rules, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        removed = _cleanup_pdfs(output_dir)
        with (run_dir / "cleanup.txt").open("w", encoding="utf-8") as f:
            f.write(f"removed_pdfs {removed}\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
