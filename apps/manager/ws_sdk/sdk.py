"""
Repo-local WebSocket SDK wrapper.

The source-of-truth implementation lives in ``sdk/src/tcm_client/sdk.py``.
This module simply re-exports the public API so tests and internal tooling
can use a stable import path within the manager application.
"""

from tcm_client.sdk import (  # type: ignore[import-not-found]
    AuthContext,
    TcmWebSocketClient,
    quickstart_queue_stats,
    run_quickstart,
)

__all__ = [
    "AuthContext",
    "TcmWebSocketClient",
    "quickstart_queue_stats",
    "run_quickstart",
]
