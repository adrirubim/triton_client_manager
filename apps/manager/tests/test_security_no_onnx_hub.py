from __future__ import annotations

import subprocess
from pathlib import Path


def test_no_onnx_hub_usage_in_repo() -> None:
    """
    Security guardrail:

    Do not use `onnx.hub.load()` (or `onnx.hub` at all) in this repository.
    The ONNX hub helper can fetch models from remote repositories and has had
    security-control bypass issues when warnings are suppressed.

    Models must be treated as controlled artifacts (filesystem / MinIO / registry),
    not fetched dynamically from GitHub at runtime.
    """

    repo_root = Path(__file__).resolve().parents[3]

    # We purposely match "code-like" patterns to avoid false positives in docs/strings.
    needles = (
        "import onnx.hub",
        "from onnx import hub",
        "onnx.hub.load(",
        "hub.load(",
    )

    # Only scan files tracked by git to avoid false positives from virtualenvs
    # (e.g. apps/manager/.venv site-packages) or local caches.
    out = subprocess.check_output(
        ["git", "ls-files", "*.py"],
        cwd=str(repo_root),
        text=True,
    )
    rel_paths = [p.strip() for p in out.splitlines() if p.strip()]

    self_path = Path(__file__).resolve()
    for rel in rel_paths:
        path = (repo_root / rel).resolve()
        if path == self_path:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(n in text for n in needles):
            raise AssertionError(
                f"Forbidden ONNX hub usage found in {path}.\n"
                "Policy: do not use `onnx.hub` / `onnx.hub.load()` in this repository."
            )

