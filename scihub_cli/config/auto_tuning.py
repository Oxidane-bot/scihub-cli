"""
Auto-tuning configuration for long-run optimization loops.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from pathlib import Path

DEFAULT_RULES = {
    "ua_overrides": {
        "curl": [],
        "browser": [],
    },
    "fast_fail_lightweight_bypass_hosts_add": [],
    "fast_fail_lightweight_bypass_hosts_drop": [],
    "fast_fail_skip_challenge_download_hosts_add": [],
    "fast_fail_skip_challenge_download_hosts_drop": [],
    "fast_fail_page_bypass_hosts_add": [],
    "fast_fail_page_bypass_hosts_drop": [],
    "fast_fail_skip_page_bypass_hosts_add": [],
    "fast_fail_skip_page_bypass_hosts_drop": [],
    "academic_host_markers_add": [],
    "academic_host_markers_drop": [],
    "non_academic_host_markers_add": [],
    "non_academic_host_markers_drop": [],
}


def _normalize_host(value: str) -> str:
    cleaned = (value or "").strip().lower()
    if cleaned.startswith("www."):
        cleaned = cleaned[4:]
    return cleaned


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        cleaned = _normalize_host(item)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        ordered.append(cleaned)
    return ordered


def _merge_domain_list(
    base: Iterable[str],
    *,
    add: Iterable[str] | None = None,
    drop: Iterable[str] | None = None,
) -> tuple[str, ...]:
    merged = { _normalize_host(item) for item in base if _normalize_host(item) }
    for item in add or []:
        cleaned = _normalize_host(item)
        if cleaned:
            merged.add(cleaned)
    for item in drop or []:
        cleaned = _normalize_host(item)
        if cleaned in merged:
            merged.remove(cleaned)
    return tuple(sorted(merged))


def get_auto_tuning_path() -> Path:
    override = os.getenv("SCIHUB_AUTO_TUNING_PATH")
    if override:
        return Path(override)
    return Path(__file__).with_name("auto_tuning.json")


def load_auto_tuning() -> dict:
    path = get_auto_tuning_path()
    if not path.exists():
        return DEFAULT_RULES.copy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return DEFAULT_RULES.copy()
    merged = DEFAULT_RULES.copy()
    merged.update(data if isinstance(data, dict) else {})
    # Normalize lists
    ua_overrides = merged.get("ua_overrides") or {}
    merged["ua_overrides"] = {
        "curl": _dedupe(ua_overrides.get("curl") or []),
        "browser": _dedupe(ua_overrides.get("browser") or []),
    }
    for key in (
        "fast_fail_lightweight_bypass_hosts_add",
        "fast_fail_lightweight_bypass_hosts_drop",
        "fast_fail_skip_challenge_download_hosts_add",
        "fast_fail_skip_challenge_download_hosts_drop",
        "fast_fail_page_bypass_hosts_add",
        "fast_fail_page_bypass_hosts_drop",
        "fast_fail_skip_page_bypass_hosts_add",
        "fast_fail_skip_page_bypass_hosts_drop",
        "academic_host_markers_add",
        "academic_host_markers_drop",
        "non_academic_host_markers_add",
        "non_academic_host_markers_drop",
    ):
        merged[key] = _dedupe(merged.get(key) or [])
    return merged


def save_auto_tuning(rules: dict) -> Path:
    path = get_auto_tuning_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


__all__ = [
    "DEFAULT_RULES",
    "get_auto_tuning_path",
    "load_auto_tuning",
    "save_auto_tuning",
    "_merge_domain_list",
]
