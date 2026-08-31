"""
File management and naming utilities.
"""

import errno
import json
import math
import os
import re
import socket
import stat
import time
from contextlib import suppress
from threading import Lock
from urllib.parse import unquote, urlparse
from uuid import uuid4

from ..config.settings import settings
from ..metadata_utils import extract_metadata, generate_filename_from_metadata
from ..utils.logging import get_logger

logger = get_logger(__name__)


class FileManager:
    """Handles file operations and naming."""

    # A lock with an owner that cannot be inspected (for example, a legacy
    # empty sidecar or a lock left by a process on another host) is retained
    # until this age.  Locks with a known, dead local PID can be reclaimed
    # immediately.  A day is comfortably longer than a normal paper download
    # while still bounding the impact of a forcefully terminated process.
    DEFAULT_RESERVATION_LOCK_TTL_SECONDS = 24 * 60 * 60
    RESERVATION_LOCK_VERSION = 1

    def __init__(
        self,
        output_dir: str = None,
        *,
        reservation_lock_ttl: float | None = None,
    ):
        self.output_dir = output_dir or settings.output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        if reservation_lock_ttl is None:
            reservation_lock_ttl = self.DEFAULT_RESERVATION_LOCK_TTL_SECONDS
        try:
            reservation_lock_ttl = float(reservation_lock_ttl)
        except (TypeError, ValueError) as e:
            raise ValueError("reservation_lock_ttl must be a positive number") from e
        if not math.isfinite(reservation_lock_ttl) or reservation_lock_ttl <= 0:
            raise ValueError("reservation_lock_ttl must be a positive number")
        self.reservation_lock_ttl = reservation_lock_ttl

        # Reservations prevent two parallel downloads (or two processes) from choosing
        # the same destination before either one has finished writing it.
        self._reservation_lock = Lock()
        self._reservations: dict[str, str] = {}
        self._reservation_tokens: dict[str, str] = {}

        # Clean up locks left by an earlier process before the first reservation.
        # The cleanup is deliberately conservative: active local owners are
        # always retained, and unknown owners require the TTL to elapse.
        self.cleanup_stale_reservation_locks()

    def generate_filename(self, doi: str, html_content: str | None = None) -> str:
        """Generate a filename based on DOI and optionally paper metadata."""
        # Default filename based on DOI
        filename = self._clean_filename(doi.replace("/", "_"))

        # If we have HTML, try to extract metadata
        if html_content:
            metadata = extract_metadata(html_content)

            if metadata and "title" in metadata and "year" in metadata:
                return generate_filename_from_metadata(metadata["title"], metadata["year"], doi)
            else:
                # Fallback to simple title extraction
                from bs4 import BeautifulSoup

                soup = BeautifulSoup(html_content, "html.parser")

                title_elem = soup.find("title")
                if title_elem and title_elem.text and "sci-hub" not in title_elem.text.lower():
                    title = title_elem.text.strip()
                    filename = self._clean_filename(title[:50])

        return f"{filename}.pdf"

    def generate_filename_from_url(self, url: str) -> str:
        """Generate a reasonable filename from a direct URL."""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return self.generate_filename(url, html_content=None)

        # Prefer the last path segment as filename
        basename = os.path.basename((parsed.path or "").rstrip("/"))
        basename = unquote(basename).strip()

        # Avoid meaningless basenames for endpoints like ".../pdf/" or ".../download"
        meaningless = {"", "pdf", "download", "index", "index.php"}
        if basename.lower() in meaningless:
            basename = f"{parsed.netloc}{parsed.path}".replace("/", "_").strip("_")

        safe = self._clean_filename(basename)
        if not safe.lower().endswith(".pdf"):
            safe = f"{safe}.pdf"
        return safe

    def get_output_path(self, filename: str) -> str:
        """Get full output path for a filename."""
        return os.path.join(self.output_dir, filename)

    def reserve_output_path(self, filename: str) -> str:
        """Return a collision-free output path and reserve it for a download.

        Existing files are never replaced.  If ``filename`` is already present, a
        numbered suffix is added before the extension (for example,
        ``paper (1).pdf``).  A small sidecar lock is created atomically so concurrent
        processes cannot select the same path during the download.
        """
        stem, suffix = os.path.splitext(filename)
        candidate_index = 0

        while True:
            candidate_name = (
                filename if candidate_index == 0 else f"{stem} ({candidate_index}){suffix}"
            )
            candidate_path = self.get_output_path(candidate_name)
            lock_path = self._reservation_lock_path(candidate_path)

            with self._reservation_lock:
                # lexists also protects dangling symlinks from being followed or
                # replaced accidentally.
                if os.path.lexists(lock_path):
                    self._cleanup_stale_reservation_lock(lock_path)
                if os.path.lexists(candidate_path) or os.path.lexists(lock_path):
                    candidate_index += 1
                    continue
                try:
                    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError:
                    candidate_index += 1
                    continue
                token = uuid4().hex
                try:
                    lock_payload = {
                        "version": self.RESERVATION_LOCK_VERSION,
                        "pid": os.getpid(),
                        "hostname": socket.gethostname(),
                        "created_at": time.time(),
                        "token": token,
                    }
                    self._write_reservation_lock(fd, lock_payload)
                except Exception:
                    with suppress(OSError):
                        os.close(fd)
                    with suppress(FileNotFoundError):
                        os.unlink(lock_path)
                    raise
                self._reservations[candidate_path] = lock_path
                self._reservation_tokens[candidate_path] = token
                return candidate_path

    def release_output_path(self, path: str, *, remove_file: bool = False) -> None:
        """Release a path reserved by :meth:`reserve_output_path`.

        ``remove_file`` should be used after a failed download so an incomplete
        destination cannot block a later attempt.  It only removes paths that this
        ``FileManager`` instance reserved.
        """
        with self._reservation_lock:
            lock_path = self._reservations.pop(path, None)
            token = self._reservation_tokens.pop(path, None)

        if lock_path is None or token is None:
            return

        if remove_file:
            with suppress(FileNotFoundError):
                os.unlink(path)

        # Only remove the sidecar still carrying our token.  If a stale-lock
        # cleanup/retry raced with release and another process acquired the
        # same path, never delete that process's active reservation.
        if self._reservation_lock_matches(lock_path, token):
            with suppress(FileNotFoundError):
                os.unlink(lock_path)

    def cleanup_stale_reservation_locks(self) -> int:
        """Remove reclaimable reservation sidecars in ``output_dir``.

        This is safe to call at startup or before a batch.  A return value is
        the number of sidecars removed.  Active locks and unknown owners that
        have not exceeded the TTL are left untouched.
        """
        removed = 0
        try:
            entries = os.scandir(self.output_dir)
        except OSError:
            return removed

        with entries:
            for entry in entries:
                if not entry.name.endswith(".scihub-cli.lock") or not entry.name.startswith("."):
                    continue
                if not self._cleanup_stale_reservation_lock(entry.path):
                    continue
                if not os.path.lexists(entry.path):
                    removed += 1
        return removed

    # Short alias for callers that do not need the implementation's full name.
    cleanup_stale_locks = cleanup_stale_reservation_locks

    @staticmethod
    def _write_reservation_lock(fd: int, payload: dict) -> None:
        """Write owner metadata to a newly-created sidecar and flush it."""
        encoded = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        remaining = memoryview(encoded)
        try:
            while remaining:
                written = os.write(fd, remaining)
                if written <= 0:
                    raise OSError("failed to write reservation lock metadata")
                remaining = remaining[written:]
            # Ensures a forced process termination does not leave a recently
            # created lock with a misleadingly empty/partial payload on normal
            # local filesystems.  If fsync is unsupported, reservation itself
            # is still valid and the TTL/metadata safeguards remain in place.
            with suppress(OSError):
                os.fsync(fd)
        finally:
            os.close(fd)

    def _cleanup_stale_reservation_lock(self, lock_path: str) -> bool:
        """Remove ``lock_path`` only when its owner is demonstrably stale."""
        try:
            stat_result = os.stat(lock_path, follow_symlinks=False)
        except FileNotFoundError:
            return True
        except OSError:
            return False

        # Do not inspect or remove symlinks/directories as lock files.  They
        # are treated as occupied, which is the safe outcome for a hostile or
        # unusual output directory.
        if not stat.S_ISREG(stat_result.st_mode):
            return False

        payload = self._read_reservation_lock(lock_path)
        if payload is not None:
            pid = payload.get("pid")
            valid_pid = isinstance(pid, int) and not isinstance(pid, bool) and pid > 0
            if valid_pid and self._reservation_owner_is_local(payload):
                # A live PID wins over age.  This prevents a long-running
                # download from being reclaimed solely because it exceeded
                # the TTL; the timestamp is only a stale-owner fallback.
                if self._is_process_alive(pid):
                    return False
                stale = True
            else:
                stale = self._reservation_age(lock_path, payload) > self.reservation_lock_ttl
        else:
            # Empty/partial/legacy sidecars cannot be associated with a PID.
            # Keep them during the short creation window and reclaim only once
            # their filesystem mtime is older than the configured TTL.
            stale = self._reservation_age(lock_path, None) > self.reservation_lock_ttl

        if not stale:
            return False
        try:
            os.unlink(lock_path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            return False

    @staticmethod
    def _read_reservation_lock(lock_path: str) -> dict | None:
        """Read a bounded JSON payload, returning ``None`` when invalid."""
        try:
            with open(lock_path, "rb") as lock_file:
                raw = lock_file.read(4096)
        except OSError:
            return None
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    @staticmethod
    def _reservation_owner_is_local(payload: dict) -> bool:
        """Return whether PID liveness can be checked on this host."""
        hostname = payload.get("hostname")
        if not hostname:
            # Early metadata versions may not include a hostname; assume local
            # so a dead PID can still be reclaimed safely.
            return True
        try:
            return str(hostname).casefold() == socket.gethostname().casefold()
        except OSError:
            return False

    @staticmethod
    def _is_process_alive(pid: object) -> bool:
        """Check PID liveness conservatively on POSIX and Windows."""
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            return False
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            # The process exists but this user cannot signal it.
            return True
        except ValueError:
            # Some Windows runtimes reject signal 0 even when PID probing is
            # otherwise available.  Keep the lock in that ambiguous case.
            return True
        except OSError as exc:
            # ESRCH is the portable POSIX "no such process" result.  Other
            # errors (including Windows permission/unsupported cases) must be
            # treated as alive to avoid deleting an active owner's lock.
            return exc.errno != errno.ESRCH
        return True

    @staticmethod
    def _reservation_age(lock_path: str, payload: dict | None) -> float:
        """Return non-negative lock age using metadata, then mtime."""
        timestamp = payload.get("created_at") if payload else None
        try:
            timestamp = float(timestamp)
            if not math.isfinite(timestamp):
                raise ValueError
        except (TypeError, ValueError):
            try:
                timestamp = os.stat(lock_path, follow_symlinks=False).st_mtime
            except OSError:
                return 0.0
        return max(0.0, time.time() - timestamp)

    @staticmethod
    def _reservation_lock_matches(lock_path: str, token: str) -> bool:
        payload = FileManager._read_reservation_lock(lock_path)
        return bool(payload and payload.get("token") == token)

    @staticmethod
    def _reservation_lock_path(path: str) -> str:
        """Return the sidecar path used to reserve an output destination."""
        directory, filename = os.path.split(path)
        return os.path.join(directory, f".{filename}.scihub-cli.lock")

    def validate_file(self, file_path: str) -> bool:
        """Validate downloaded file."""
        if not os.path.exists(file_path):
            return False

        file_size = os.path.getsize(file_path)
        if file_size < settings.MIN_FILE_SIZE:
            logger.warning(f"Downloaded file is suspiciously small: {file_size} bytes")
            return False

        return True

    def _clean_filename(self, filename: str) -> str:
        """Create a safe filename from potentially unsafe string."""
        # Replace unsafe characters
        unsafe_chars = r'[<>:"/\\|?*]'
        filename = re.sub(unsafe_chars, "_", filename)

        # Limit length
        if len(filename) > settings.MAX_FILENAME_LENGTH:
            filename = filename[: settings.MAX_FILENAME_LENGTH]

        return filename
