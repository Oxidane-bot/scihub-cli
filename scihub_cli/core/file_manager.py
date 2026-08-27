"""
File management and naming utilities.
"""

import os
import re
from contextlib import suppress
from threading import Lock
from urllib.parse import unquote, urlparse

from ..config.settings import settings
from ..metadata_utils import extract_metadata, generate_filename_from_metadata
from ..utils.logging import get_logger

logger = get_logger(__name__)


class FileManager:
    """Handles file operations and naming."""

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or settings.output_dir
        os.makedirs(self.output_dir, exist_ok=True)
        # Reservations prevent two parallel downloads (or two processes) from choosing
        # the same destination before either one has finished writing it.
        self._reservation_lock = Lock()
        self._reservations: dict[str, str] = {}

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
                if os.path.lexists(candidate_path) or os.path.lexists(lock_path):
                    candidate_index += 1
                    continue
                try:
                    fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                except FileExistsError:
                    candidate_index += 1
                    continue
                os.close(fd)
                self._reservations[candidate_path] = lock_path
                return candidate_path

    def release_output_path(self, path: str, *, remove_file: bool = False) -> None:
        """Release a path reserved by :meth:`reserve_output_path`.

        ``remove_file`` should be used after a failed download so an incomplete
        destination cannot block a later attempt.  It only removes paths that this
        ``FileManager`` instance reserved.
        """
        with self._reservation_lock:
            lock_path = self._reservations.pop(path, None)

        if lock_path is None:
            return

        if remove_file:
            with suppress(FileNotFoundError):
                os.unlink(path)

        with suppress(FileNotFoundError):
            os.unlink(lock_path)

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
