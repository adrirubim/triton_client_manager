"""
Small, standalone Python SDK for Triton Client Manager's WebSocket API.

This module is a packaging-friendly version of the internal SDK that lives
under ``apps/manager/ws_sdk/sdk.py`` in the main repository. It is meant
to be installed as a regular Python package (``tcm-client``) and used by
integrators without needing to vendor or copy code from the server repo.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from types import TracebackType
from typing import Any, Dict, List, Optional, Sequence, Type

import numpy as np
from pydantic import BaseModel, Field, ValidationError

try:
    # Prefer the modern asyncio client API when available (websockets >= 12).
    from websockets.asyncio.client import connect  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - fallback for older layouts
    # Fallback for environments where the asyncio submodule is not exposed.
    from websockets.client import connect  # type: ignore[no-redef]

JsonDict = Dict[str, Any]


@dataclass
class AuthContext:
    uuid: str
    token: Optional[str] = None
    sub: Optional[str] = None
    tenant_id: Optional[str] = None
    roles: Optional[List[str]] = None


class AuthClientInfo(BaseModel):
    sub: str
    tenant_id: str
    roles: List[str] = Field(default_factory=list)


class AuthPayload(BaseModel):
    token: Optional[str] = None
    client: Optional[AuthClientInfo] = None


class BaseRequest(BaseModel):
    uuid: str
    type: str
    payload: Dict[str, Any]


class InferenceInput(BaseModel):
    name: str
    shape: List[int]
    datatype: str
    data: Any


class InferenceRequestPayload(BaseModel):
    vm_id: str
    vm_ip: Optional[str] = None
    container_id: str
    model_name: Optional[str] = None
    inputs: Optional[List[InferenceInput]] = None
    pipeline: Optional[List[Dict[str, Any]]] = None
    request: Dict[str, Any] = Field(default_factory=lambda: {"protocol": "http"})


class InferenceRequest(BaseRequest):
    type: str = "inference"
    payload: InferenceRequestPayload


class InferenceResponse(BaseModel):
    type: str
    payload: Dict[str, Any]


class TcmWebSocketClient:
    """
    High-level WebSocket client for Triton Client Manager.

    Typical usage:

        async with TcmWebSocketClient("ws://127.0.0.1:8000/ws", auth_ctx) as client:
            await client.auth()
            stats = await client.info_queue_stats()
    """

    def __init__(
        self,
        uri: str,
        auth_ctx: AuthContext,
        *,
        connect_timeout_seconds: float = 10.0,
        message_timeout_seconds: float = 30.0,
    ):
        self._uri = uri
        self._auth_ctx = auth_ctx
        self._connect_timeout_seconds = connect_timeout_seconds
        self._message_timeout_seconds = message_timeout_seconds
        # Do not use strict typing here to avoid hard-coupling to a specific
        # websockets library version.
        self._sock: Optional[Any] = None

    async def __aenter__(self) -> "TcmWebSocketClient":
        self._sock = await asyncio.wait_for(
            connect(self._uri),
            timeout=self._connect_timeout_seconds,
        )
        return self

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        if self._sock is not None:
            await self._sock.close()
            self._sock = None

    async def _send(self, message: JsonDict) -> JsonDict:
        if self._sock is None:
            raise RuntimeError(
                "WebSocket not connected; use 'async with' or call connect() first"
            )
        await asyncio.wait_for(
            self._sock.send(json.dumps(message)),
            timeout=self._message_timeout_seconds,
        )
        raw = await asyncio.wait_for(
            self._sock.recv(),
            timeout=self._message_timeout_seconds,
        )
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

        auth_payload = AuthPayload(
            token=self._auth_ctx.token,
            client=AuthClientInfo(
                sub=self._auth_ctx.sub or self._auth_ctx.uuid,
                tenant_id=self._auth_ctx.tenant_id or "dev-tenant",
                roles=self._auth_ctx.roles or [],
            )
            if payload
            else None,
        )

        msg = BaseRequest(uuid=self._auth_ctx.uuid, type="auth", payload=auth_payload.model_dump(exclude_none=True))
        resp = await self._send(msg.model_dump())
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

    async def management_creation(self, action: str = "creation", **kwargs: Any) -> JsonDict:
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
        inputs: Sequence[InferenceInput],
        *,
        vm_ip: Optional[str] = None,
    ) -> JsonDict:
        """
        Send a minimal HTTP inference request.
        """
        payload = InferenceRequestPayload(
            vm_id=vm_id,
            vm_ip=vm_ip,
            container_id=container_id,
            model_name=model_name,
            request={"protocol": "http", "inputs": [i.model_dump() for i in inputs]},
        )
        request = InferenceRequest(uuid=self._auth_ctx.uuid, payload=payload)
        resp = await self._send(request.model_dump())
        return resp

    async def inference_pipeline(
        self,
        vm_id: str,
        container_id: str,
        pipeline: List[JsonDict],
    ) -> JsonDict:
        """
        Send a simple HTTP pipeline (multi-model, sequential) inference request.

        The `pipeline` argument is a list of JSON dicts, each describing one
        step with at least:

        - name (optional, string)
        - model_name (string)
        - protocol (optional, defaults to "http")
        - inputs (list of Triton input dicts)
        """
        payload = InferenceRequestPayload(
            vm_id=vm_id,
            container_id=container_id,
            pipeline=pipeline,
        )
        request = InferenceRequest(uuid=self._auth_ctx.uuid, payload=payload)
        resp = await self._send(request.model_dump())
        return resp


class TcmClient:
    """
    Synchronous, high-level helper that wraps the async WebSocket client.

    It takes care of:
    - opening/closing the WebSocket,
    - performing the auth handshake,
    - sending a single inference request and validating the response.
    """

    def __init__(self, uri: str, auth_ctx: AuthContext) -> None:
        self._uri = uri
        self._auth_ctx = auth_ctx

    def infer(
        self,
        vm_id: str,
        container_id: str,
        model_name: str,
        inputs: Sequence[InferenceInput],
        *,
        vm_ip: Optional[str] = None,
    ) -> InferenceResponse:
        """
        High-level synchronous helper for a single HTTP-style inference.

        Usage:

            client = TcmClient("ws://127.0.0.1:8000/ws", auth_ctx)
            result = client.infer("vm-1", "ctr-1", "model", inputs, vm_ip="192.0.2.10")
        """

        async def _run() -> InferenceResponse:
            async with TcmWebSocketClient(self._uri, self._auth_ctx) as client:
                await client.auth()
                raw = await client.inference_http(
                    vm_id=vm_id,
                    vm_ip=vm_ip,
                    container_id=container_id,
                    model_name=model_name,
                    inputs=inputs,
                )
                return InferenceResponse(type=raw.get("type", ""), payload=raw.get("payload", {}))

        return asyncio.run(_run())

    def run_inference(
        self,
        vm_id: str,
        container_id: str,
        model_name: str,
        data: np.ndarray | List[float],
        *,
        vm_ip: Optional[str] = None,
        input_name: str = "INPUT__0",
        datatype: str = "FP32",
    ) -> InferenceResponse:
        """
        Convenience helper that builds a single `InferenceInput` from raw numeric data.

        This forces callers to go through the strongly-typed DTO path while still
        offering a simple entrypoint for common use cases.
        """

        if isinstance(data, list):
            array = np.asarray(data, dtype=np.float32)
        elif isinstance(data, np.ndarray):
            if data.dtype != np.float32:
                array = data.astype(np.float32)
            else:
                array = data
        else:  # pragma: no cover - defensive, typing should prevent this
            raise TypeError(f"Unsupported data type for run_inference: {type(data)!r}")

        flat = array.reshape(-1).tolist()
        shape = list(array.shape) if array.shape else [len(flat)]

        try:
            inference_input = InferenceInput(
                name=input_name,
                shape=shape,
                datatype=datatype,
                data=flat,
            )
        except ValidationError as exc:  # pragma: no cover - unexpected schema errors
            raise ValueError(f"Invalid inference input: {exc}") from exc

        return self.infer(
            vm_id=vm_id,
            vm_ip=vm_ip,
            container_id=container_id,
            model_name=model_name,
            inputs=[inference_input],
        )


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

