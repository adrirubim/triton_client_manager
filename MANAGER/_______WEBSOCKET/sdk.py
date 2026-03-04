"""
Pequeño SDK cliente para Triton Client Manager (WebSocket).

Objetivos:
- Encapsular la conexión WebSocket (`/ws`).
- Proporcionar métodos de alto nivel:
  - `auth(...)`
  - `info_queue_stats()`
  - `management_creation(...)`
  - `inference_http(...)`

Pensado para integradores (backends/servicios) y para tests de contrato.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from websockets.asyncio.client import connect

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
    Cliente WebSocket de alto nivel.

    Uso típico:

        async with TcmWebSocketClient("ws://127.0.0.1:8000/ws", auth_ctx) as client:
            await client.auth()
            stats = await client.info_queue_stats()
    """

    def __init__(self, uri: str, auth_ctx: AuthContext):
        self._uri = uri
        self._auth_ctx = auth_ctx
        # No tipado estricto para evitar dependencias de versión de websockets
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
        """Envía el mensaje de auth según el contrato estándar."""
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
        """Solicita `info.queue_stats` y devuelve el payload de respuesta."""
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
        Envía un mensaje de tipo `management` genérico.

        Solo garantiza el contrato básico de respuesta (`status` en payload).
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

    async def inference_http(self, model_name: str, inputs: JsonDict) -> JsonDict:
        """
        Envía una petición de inferencia HTTP mínima.
        """
        msg: JsonDict = {
            "uuid": self._auth_ctx.uuid,
            "type": "inference",
            "payload": {
                "model_name": model_name,
                "request": {
                    "protocol": "http",
                    "inputs": inputs,
                },
            },
        }
        return await self._send(msg)


async def quickstart_queue_stats(uri: str) -> JsonDict:
    """
    Quickstart de referencia:
    - Conecta.
    - Hace auth con un rol de ejemplo.
    - Pide `info.queue_stats`.
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
    Punto de entrada sincrónico para el quickstart.
    """
    result = asyncio.run(quickstart_queue_stats(uri))
    print(json.dumps(result, indent=2))


__all__ = [
    "AuthContext",
    "TcmWebSocketClient",
    "quickstart_queue_stats",
    "run_quickstart",
]
