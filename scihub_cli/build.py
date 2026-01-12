"""Custom setuptools commands to keep wheels bytecode-free."""

from __future__ import annotations

import os
import shutil
from contextlib import suppress
from pathlib import Path

from setuptools.command.build_py import build_py as _build_py


class NoBytecodeBuildPy(_build_py):
    """Disable bytecode compilation and strip cached bytecode from build output."""

    def byte_compile(self, files):  # noqa: D401
        """Skip bytecode compilation to avoid __pycache__ in wheels."""
        return

    def run(self):
        super().run()
        self._prune_bytecode(Path(self.build_lib))

    def _prune_bytecode(self, root: Path) -> None:
        if not root.exists():
            return
        for dirpath, dirnames, filenames in os.walk(root):
            for dirname in list(dirnames):
                if dirname == "__pycache__":
                    shutil.rmtree(Path(dirpath) / dirname, ignore_errors=True)
                    dirnames.remove(dirname)
            for filename in filenames:
                if filename.endswith((".pyc", ".pyo")):
                    with suppress(FileNotFoundError):
                        (Path(dirpath) / filename).unlink()
