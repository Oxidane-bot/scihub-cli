import os
import subprocess
from pathlib import Path

import pytest


def _integration_enabled() -> bool:
    return os.getenv("SCIHUB_CLI_RUN_INTEGRATION", "").lower() in {"1", "true", "yes"}


@pytest.mark.skipif(
    not _integration_enabled(),
    reason="End-to-end integration test is opt-in via SCIHUB_CLI_RUN_INTEGRATION=1",
)
def test_e2e_install_and_download():
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "integration_test.sh"
    assert script.exists(), f"Missing integration test script: {script}"

    proc = subprocess.run(
        ["bash", str(script)],
        cwd=str(repo_root),
        text=True,
        capture_output=True,
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\n\nstderr:\n{proc.stderr}"
