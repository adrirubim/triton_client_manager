from __future__ import annotations

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
    candidates = [
        repo_root / "apps" / "manager",
        repo_root / "sdk",
        repo_root / "examples",
        repo_root / "src",
    ]

    needles = (
        "onnx.hub",
        "onnx.hub.load",
        "hub.load(",
        "import onnx.hub",
        "from onnx import hub",
    )

    for base in candidates:
        if not base.exists():
            continue

        for path in base.rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(n in text for n in needles):
                raise AssertionError(
                    f"Forbidden ONNX hub usage found in {path}.\n"
                    "Policy: do not use `onnx.hub` / `onnx.hub.load()` in this repository."
                )

