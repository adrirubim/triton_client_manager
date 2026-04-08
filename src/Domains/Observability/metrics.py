from __future__ import annotations

from collections.abc import Callable
from typing import Optional

_emit_model_analysis_issue: Optional[Callable[[str], None]] = None


def set_model_analysis_issue_emitter(fn: Callable[[str], None] | None) -> None:
    """
    Register a callback used by domain actions to emit model-analysis issue metrics.

    The domain layer must remain decoupled from the manager runtime and Prometheus.
    When running inside the manager, apps/manager/utils/metrics.py registers a callback.
    """

    global _emit_model_analysis_issue
    _emit_model_analysis_issue = fn


def emit_model_analysis_issue(code: str) -> None:
    """Emit a model-analysis issue code (no-op if not configured)."""

    fn = _emit_model_analysis_issue
    if fn is None:
        return
    try:
        fn(code)
    except Exception:
        # Metrics must never break the primary execution path.
        return


__all__ = ["emit_model_analysis_issue", "set_model_analysis_issue_emitter"]
