from __future__ import annotations

import sys
from pathlib import Path

# Canonical implementation lives in the SDK to avoid drift.
# Make `tcm_client` importable from this repo checkout without installation.
_repo_root = Path(__file__).resolve().parents[4]
_sdk_src = _repo_root / "sdk" / "src"
sys.path.insert(0, str(_sdk_src))

from tcm_client.model_analyze import (  # noqa: E402
    AnalyzeModelAction,
    AnalyzeModelReport,
    AnalyzedIO,
)

__all__ = ["AnalyzeModelAction", "AnalyzeModelReport", "AnalyzedIO"]

