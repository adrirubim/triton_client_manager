from __future__ import annotations

import subprocess
from pathlib import Path


def _list_repo_python_files(repo_root: Path) -> list[Path]:
    """
    Return Python source files to scan.

    Prefer `git ls-files` (stable + avoids venv/caches). If git is unavailable
    (e.g. minimal Docker image), fall back to a filesystem walk with sensible
    excludes.
    """
    try:
        out = subprocess.check_output(
            ["git", "ls-files", "*.py"],
            cwd=str(repo_root),
            text=True,
        )
        rel_paths = [p.strip() for p in out.splitlines() if p.strip()]
        return [(repo_root / rel).resolve() for rel in rel_paths]
    except (FileNotFoundError, subprocess.CalledProcessError, OSError):
        excluded_dirs = {
            ".git",
            ".venv",
            "venv",
            "__pycache__",
            "node_modules",
            "dist",
            "build",
            ".mypy_cache",
            ".pytest_cache",
        }
        files: list[Path] = []
        for path in repo_root.rglob("*.py"):
            if any(part in excluded_dirs for part in path.parts):
                continue
            files.append(path.resolve())
        return files


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

    self_path = Path(__file__).resolve()
    for path in _list_repo_python_files(repo_root):
        if path == self_path:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(n in text for n in needles):
            raise AssertionError(
                f"Forbidden ONNX hub usage found in {path}.\n"
                "Policy: do not use `onnx.hub` / `onnx.hub.load()` in this repository."
            )
