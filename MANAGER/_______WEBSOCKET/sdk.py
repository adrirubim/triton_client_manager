"""
Small client SDK for Triton Client Manager (WebSocket).

Goals:
- Encapsulate the WebSocket connection (`/ws`).
- Provide high-level methods:
  - `auth(...)`
  - `info_queue_stats()`
  - `management_creation(...)`
  - `inference_http(...)`

Intended for integrators (backends/services) and contract tests.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    # Prefer the modern asyncio client API when available.
    from websockets.asyncio.client import connect  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - fallback for older layouts
    from websockets.client import connect  # type: ignore[no-redef]

JsonDict = Dict[str, Any]


@dataclass
class AuthContext:
    uuid: str
    token: Optional[str] = None
    sub: Optional[str] = None
    tenant_id: Optional[str] = None
    roles: Optional[List[str]] = None


class TcmWebSocketClient:
    """
    High-level WebSocket client.

    Typical usage:

        async with TcmWebSocketClient("ws://127.0.0.1:8000/ws", auth_ctx) as client:
            await client.auth()
            stats = await client.info_queue_stats()
    """

    def __init__(self, uri: str, auth_ctx: AuthContext):
        self._uri = uri
        self._auth_ctx = auth_ctx
        # Do not use strict typing here to avoid hard-coupling to a specific
        # websockets library version.
        self._sock: Optional[Any] = None

    async def __aenter__(self) -> "TcmWebSocketClient":
        self._sock = await connect(self._uri)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._sock is not None:
            await self._sock.close()
            self._sock = None

    async def _send(self, message: JsonDict) -> JsonDict:
        if self._sock is None:
            raise RuntimeError(
                "WebSocket not connected; use 'async with' or call connect() first"
            )
        await self._sock.send(json.dumps(message))
        raw = await self._sock.recv()
        return json.loads(raw)

    async def auth(self) -> JsonDict:
        """Send the auth message following the standard contract."""
        payload: JsonDict = {}
        if any(
            [
                self._auth_ctx.token,
                self._auth_ctx.sub,
                self._auth_ctx.tenant_id,
                self._auth_ctx.roles,
            ]
        ):
            payload = {
                "token": self._auth_ctx.token,
                "client": {
                    "sub": self._auth_ctx.sub or self._auth_ctx.uuid,
                    "tenant_id": self._auth_ctx.tenant_id or "dev-tenant",
                    "roles": self._auth_ctx.roles or [],
                },
            }

        msg: JsonDict = {
            "uuid": self._auth_ctx.uuid,
            "type": "auth",
            "payload": payload,
        }
        resp = await self._send(msg)
        if resp.get("type") != "auth.ok":
            raise RuntimeError(f"Auth failed: {resp}")
        return resp

    async def info_queue_stats(self) -> JsonDict:
        """Request `info.queue_stats` and return the response payload."""
        msg: JsonDict = {
            "uuid": self._auth_ctx.uuid,
            "type": "info",
            "payload": {"action": "queue_stats"},
        }
        resp = await self._send(msg)
        if resp.get("type") != "info_response":
            raise RuntimeError(f"Unexpected info response: {resp}")
        return resp

    async def management_creation(
        self, action: str = "creation", **kwargs: Any
    ) -> JsonDict:
        """
        Send a generic `management` message.

        Only the basic response contract is guaranteed (`status` in payload).
        """
        msg: JsonDict = {
            "uuid": self._auth_ctx.uuid,
            "type": "management",
            "payload": {
                "action": action,
                **kwargs,
            },
        }
        return await self._send(msg)

    async def inference_http(
        self,
        vm_id: str,
        container_id: str,
        model_name: str,
        inputs: list[JsonDict],
    ) -> JsonDict:
        """
        Send a minimal HTTP inference request.
        """
        msg: JsonDict = {
            "uuid": self._auth_ctx.uuid,
            "type": "inference",
            "payload": {
                "vm_id": vm_id,
                "container_id": container_id,
                "model_name": model_name,
                "inputs": inputs,
                "request": {"protocol": "http"},
            },
        }
        return await self._send(msg)


async def quickstart_queue_stats(uri: str) -> JsonDict:
    """
    Reference quickstart:
    - Connect.
    - Perform auth with an example role set.
    - Request `info.queue_stats`.
    """
    ctx = AuthContext(
        uuid="sdk-quickstart-client",
        token="dummy-token",
        sub="user-sdk",
        tenant_id="tenant-sdk",
        roles=["inference", "management"],
    )
    async with TcmWebSocketClient(uri, ctx) as client:
        await client.auth()
        return await client.info_queue_stats()


def run_quickstart(uri: str) -> None:
    """
    Synchronous entrypoint for the quickstart.
    """
    result = asyncio.run(quickstart_queue_stats(uri))
    print(json.dumps(result, indent=2))


__all__ = [
    "AuthContext",
    "TcmWebSocketClient",
    "quickstart_queue_stats",
    "run_quickstart",
]
