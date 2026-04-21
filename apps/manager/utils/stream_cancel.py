"""
Lightweight cancellation registry for in-flight operations keyed by client_id.

Goal: abort expensive backend work (e.g. Triton gRPC streaming) immediately when
the WebSocket client disconnects or delivery fails, preventing zombie compute.
"""

from __future__ import annotations

import threading
from typing import Dict, Optional

_lock = threading.Lock()
_events: Dict[str, threading.Event] = {}


def get_or_create(client_id: str) -> threading.Event:
    cid = str(client_id or "")
    ev = None
    with _lock:
        ev = _events.get(cid)
        if ev is None:
            ev = threading.Event()
            _events[cid] = ev
    return ev


def cancel(client_id: str) -> None:
    cid = str(client_id or "")
    with _lock:
        ev = _events.get(cid)
    if ev is not None:
        ev.set()


def clear(client_id: str) -> None:
    """
    Clear and remove cancellation state for the client_id.
    """
    cid = str(client_id or "")
    with _lock:
        ev = _events.pop(cid, None)
    if ev is not None:
        try:
            ev.clear()
        except Exception:
            pass


def peek(client_id: str) -> Optional[threading.Event]:
    cid = str(client_id or "")
    with _lock:
        return _events.get(cid)


def cancel_all() -> None:
    """
    Best-effort: signal cancellation for all in-flight operations.
    Used during hard shutdown to guarantee streams don't block process exit.
    """
    with _lock:
        events = list(_events.values())
    for ev in events:
        try:
            ev.set()
        except Exception:
            pass

