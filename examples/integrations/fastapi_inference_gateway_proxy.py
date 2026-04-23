from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import Body, FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse

from tcm_client import AuthContext, TcmWebSocketClient

JsonDict = Dict[str, Any]


def _manager_http_base() -> str:
    return os.getenv("TCM_HTTP_BASE", "http://127.0.0.1:8000").rstrip("/")


def _manager_ws_uri() -> str:
    return os.getenv("TCM_WS_URI", "ws://127.0.0.1:8000/ws")


def _build_auth_context() -> AuthContext:
    uuid = os.getenv("TCM_CLIENT_UUID", "gateway-proxy")
    token = os.getenv("TCM_CLIENT_TOKEN", "dummy-token")
    sub = os.getenv("TCM_CLIENT_SUB", uuid)
    tenant_id = os.getenv("TCM_CLIENT_TENANT_ID", "tenant-sdk")
    roles = [r.strip() for r in os.getenv("TCM_CLIENT_ROLES", "inference").split(",") if r.strip()]
    return AuthContext(uuid=uuid, token=token, sub=sub, tenant_id=tenant_id, roles=roles)


def _ready_probe() -> Tuple[bool, Optional[str], JsonDict]:
    """
    v2.0.0-GOLDEN contract: /ready may return 503 with a sanitized payload that includes error_id.
    The proxy must propagate that error_id for correlation.
    """
    try:
        res = requests.get(_manager_http_base() + "/ready", timeout=1.5)
    except Exception as exc:
        # Never expose exception text to external callers (security hardening).
        # Keep a local correlation handle for logs/triage.
        local_error_id = str(uuid.uuid4())
        return (
            False,
            local_error_id,
            {"status": "not_ready", "reason": "probe_failed", "detail": "upstream_unreachable"},
        )

    try:
        payload = res.json()
    except Exception:
        payload = {"status": "unknown", "detail": res.text}

    if res.status_code == 200:
        return True, None, payload
    return False, payload.get("error_id"), payload


def _auth_message(ctx: AuthContext) -> JsonDict:
    payload: JsonDict = {
        "token": ctx.token,
        "client": {
            "sub": ctx.sub or ctx.uuid,
            "tenant_id": ctx.tenant_id or "dev-tenant",
            "roles": ctx.roles or [],
        },
        "capability": ["json", "shm"],
    }
    return {"uuid": ctx.uuid, "type": "auth", "payload": payload}


def _inference_message(
    *,
    ctx: AuthContext,
    vm_id: str,
    vm_ip: Optional[str],
    container_id: str,
    model_name: str,
    inputs: List[JsonDict],
    allow_transient: bool,
) -> JsonDict:
    payload: JsonDict = {
        "vm_id": vm_id,
        "container_id": container_id,
        "model_name": model_name,
        "request": {
            "protocol": "http",
            "inputs": inputs,
            "allow_transient": bool(allow_transient),
        },
    }
    if vm_ip:
        payload["vm_ip"] = vm_ip
    return {"uuid": ctx.uuid, "type": "inference", "payload": payload}


@dataclass
class ClientPool:
    """
    Minimal pool: one persistent WebSocket per process.
    This keeps connection/auth overhead low while staying simple and robust.
    """

    ws_uri: str
    ctx: AuthContext
    _client: Optional[TcmWebSocketClient] = None

    async def get(self) -> TcmWebSocketClient:
        if self._client is not None:
            return self._client

        client = TcmWebSocketClient(self.ws_uri, self.ctx)
        await client.__aenter__()
        try:
            resp = await client._send(_auth_message(self.ctx))  # type: ignore[attr-defined]
            if resp.get("type") != "auth.ok":
                raise RuntimeError(f"Auth failed: {resp}")
        except Exception:
            await client.__aexit__(None, None, None)
            raise

        self._client = client
        return client

    async def reset(self) -> None:
        if self._client is None:
            return
        try:
            await self._client.__aexit__(None, None, None)
        finally:
            self._client = None


app = FastAPI(title="Inference Gateway Proxy (FastAPI + TCM) — v2.0.0-GOLDEN")


@app.on_event("startup")
async def startup() -> None:
    app.state.pool = ClientPool(ws_uri=_manager_ws_uri(), ctx=_build_auth_context())


@app.on_event("shutdown")
async def shutdown() -> None:
    pool: ClientPool = app.state.pool
    await pool.reset()


@app.get("/healthz")
def healthz() -> JsonDict:
    return {"status": "ok", "service": "tcm-gateway-proxy"}


@app.get("/readyz")
def readyz(response: Response) -> JsonDict:
    ok, error_id, payload = _ready_probe()
    if ok:
        return {"status": "ready", "upstream": payload}

    # Propagate manager correlation handle.
    response.status_code = 503
    return {
        "status": "not_ready",
        "upstream": payload,
        "error_id": error_id,
    }


@app.post("/v1/infer/{vm_id}/{container_id}/{model_name}")
async def infer(
    vm_id: str,
    container_id: str,
    model_name: str,
    inputs: List[JsonDict] = Body(..., description="Lista de inputs Triton (JSON tensor o SHMReference)"),
    vm_ip: Optional[str] = None,
    allow_transient: bool = False,
) -> JsonDict:
    """
    Gateway Proxy:
    - recibe tensores o SHMReference desde clientes HTTP
    - ejecuta inferencia vía Manager WebSocket
    - retorna la respuesta del Manager sin perder semántica (status/codes/error payload)
    """
    pool: ClientPool = app.state.pool
    t0 = time.perf_counter()

    try:
        client = await pool.get()
        msg = _inference_message(
            ctx=pool.ctx,
            vm_id=vm_id,
            vm_ip=vm_ip,
            container_id=container_id,
            model_name=model_name,
            inputs=inputs,
            allow_transient=allow_transient,
        )
        resp = await client._send(msg)  # type: ignore[attr-defined]
    except Exception as exc:
        # On transport errors, reset the pool so next request reconnects cleanly.
        await pool.reset()
        # Do not leak exception details to external callers. Return a sanitized error
        # with a correlation handle.
        error_id = str(uuid.uuid4())
        return JSONResponse(
            status_code=502,
            content={
                "status": "error",
                "code": "UPSTREAM_TRANSPORT_ERROR",
                "message": "Upstream transport failure while contacting Manager",
                "error_id": error_id,
            },
        )
    finally:
        t1 = time.perf_counter()

    return {"latency_ms": (t1 - t0) * 1000.0, "manager_response": resp}
