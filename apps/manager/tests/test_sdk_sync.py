from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_vendored_sdk_is_in_sync() -> None:
    # tests/ vive en apps/manager/tests, por lo que el root del repo
    # está tres niveles por encima de este archivo.
    repo_root = Path(__file__).resolve().parents[3]
    script = repo_root / "scripts" / "sync_sdk.py"
    assert script.exists(), f"Missing sync script: {script}"

    proc = subprocess.run(
        [sys.executable, str(script), "--check"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
