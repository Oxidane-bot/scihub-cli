from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

from scihub_cli.core.file_manager import FileManager


def _write_lock(path: Path, payload: dict | None = None) -> None:
    if payload is None:
        path.touch()
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


def test_dead_pid_lock_is_reclaimed_before_reserving(tmp_path: Path, monkeypatch):
    lock_path = tmp_path / ".paper.pdf.scihub-cli.lock"
    _write_lock(
        lock_path,
        {
            "version": 1,
            "pid": 123,
            "hostname": socket.gethostname(),
            "created_at": time.time(),
            "token": "dead-owner",
        },
    )
    monkeypatch.setattr(FileManager, "_is_process_alive", staticmethod(lambda _pid: False))

    manager = FileManager(str(tmp_path), reservation_lock_ttl=3600)
    reserved = manager.reserve_output_path("paper.pdf")

    assert Path(reserved).name == "paper.pdf"
    manager.release_output_path(reserved, remove_file=True)


def test_live_pid_lock_is_not_reclaimed_by_ttl(tmp_path: Path):
    manager = FileManager(str(tmp_path), reservation_lock_ttl=0.01)
    lock_path = tmp_path / ".paper.pdf.scihub-cli.lock"
    _write_lock(
        lock_path,
        {
            "version": 1,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "created_at": time.time() - 3600,
            "token": "active-owner",
        },
    )

    reserved = manager.reserve_output_path("paper.pdf")

    assert Path(reserved).name == "paper (1).pdf"
    assert lock_path.exists()
    manager.release_output_path(reserved, remove_file=True)
    lock_path.unlink()


def test_unknown_legacy_lock_uses_ttl_before_reclamation(tmp_path: Path):
    manager = FileManager(str(tmp_path), reservation_lock_ttl=60)
    lock_path = tmp_path / ".paper.pdf.scihub-cli.lock"
    _write_lock(lock_path)

    reserved = manager.reserve_output_path("paper.pdf")
    assert Path(reserved).name == "paper (1).pdf"
    manager.release_output_path(reserved, remove_file=True)

    old = time.time() - 120
    os.utime(lock_path, (old, old))
    reclaimed = manager.reserve_output_path("paper.pdf")

    assert Path(reclaimed).name == "paper.pdf"
    manager.release_output_path(reclaimed, remove_file=True)
