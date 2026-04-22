from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests

from tcm_client import AuthContext, TcmWebSocketClient

JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class RetryPolicy:
    """
    Recommended retry policy (v2.0.0-GOLDEN):
    - SYSTEM_SHUTDOWN: stop-the-world, reconnect with backoff, wait for readiness.
    - Triton structured errors: retry iff retriable=true, respecting retry_after_seconds if present.
    """

    max_attempts: int = 7
    base_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 8.0
    jitter_ratio: float = 0.2

    def backoff(self, attempt: int, *, server_hint_seconds: Optional[float] = None) -> float:
        if server_hint_seconds is not None and server_hint_seconds > 0:
            return float(server_hint_seconds)
        exp = min(self.max_backoff_seconds, self.base_backoff_seconds * (2**max(0, attempt - 1)))
        jitter = exp * self.jitter_ratio * random.random()
        return min(self.max_backoff_seconds, exp + jitter)


def _ready_check(manager_http_base: str, *, timeout_seconds: float = 1.5) -> Tuple[bool, Optional[str], JsonDict]:
    url = manager_http_base.rstrip("/") + "/ready"
    try:
        res = requests.get(url, timeout=timeout_seconds)
    except Exception as exc:
        return False, None, {"status": "not_ready", "reason": "probe_failed", "detail": str(exc)}

    try:
        payload = res.json()
    except Exception:
        payload = {"status": "unknown", "detail": res.text}

    if res.status_code == 200:
        return True, None, payload
    return False, payload.get("error_id"), payload


def _build_auth_message(ctx: AuthContext) -> JsonDict:
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


def _build_infer_message(
    *,
    ctx: AuthContext,
    vm_id: str,
    vm_ip: Optional[str],
    container_id: str,
    model_name: str,
    inputs: list[JsonDict],
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


def _extract_typed_triton_error(resp: JsonDict) -> Optional[JsonDict]:
    if resp.get("type") != "inference":
        return None
    payload = resp.get("payload") or {}
    if payload.get("status") != "FAILED":
        return None
    data = (payload.get("data") or {}) if isinstance(payload.get("data"), dict) else None
    if not data:
        return None
    if "code" not in data or "retriable" not in data:
        return None
    return data


async def _connect_and_auth(ws_uri: str, ctx: AuthContext) -> TcmWebSocketClient:
    client = TcmWebSocketClient(ws_uri, ctx)
    await client.__aenter__()
    try:
        auth_resp = await client._send(_build_auth_message(ctx))  # type: ignore[attr-defined]
        if auth_resp.get("type") != "auth.ok":
            raise RuntimeError(f"Auth failed: {auth_resp}")
        return client
    except Exception:
        await client.__aexit__(None, None, None)
        raise


async def orchestrate_with_retries() -> None:
    parser = argparse.ArgumentParser(description="Resilient Async Orchestrator (Retries + Backoff) — v2.0.0-GOLDEN")
    parser.add_argument("--ws-uri", default=os.getenv("TCM_WS_URI", "ws://127.0.0.1:8000/ws"))
    parser.add_argument("--manager-http-base", default=os.getenv("TCM_HTTP_BASE", "http://127.0.0.1:8000"))
    parser.add_argument("--vm-id", required=True)
    parser.add_argument("--vm-ip", default=os.getenv("TCM_VM_IP"))
    parser.add_argument("--container-id", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--allow-transient", action="store_true")
    args = parser.parse_args()

    policy = RetryPolicy()
    ctx = AuthContext(
        uuid=os.getenv("TCM_CLIENT_UUID", "resilient-orchestrator"),
        token=os.getenv("TCM_CLIENT_TOKEN", "dummy-token"),
        sub=os.getenv("TCM_CLIENT_SUB", "resilient-user"),
        tenant_id=os.getenv("TCM_CLIENT_TENANT_ID", "tenant-sdk"),
        roles=[r.strip() for r in os.getenv("TCM_CLIENT_ROLES", "inference").split(",") if r.strip()],
    )

    # Example input (JSON tensor path). Swap with SHMReference for large tensors.
    inputs: list[JsonDict] = [
        {
            "name": "INPUT__0",
            "shape": [1, 3, 224, 224],
            "datatype": "FP32",
            "data": [0.0] * (1 * 3 * 224 * 224),
        }
    ]

    attempt = 0
    client: Optional[TcmWebSocketClient] = None

    while attempt < policy.max_attempts:
        attempt += 1
        try:
            if client is None:
                client = await _connect_and_auth(args.ws_uri, ctx)

            infer_msg = _build_infer_message(
                ctx=ctx,
                vm_id=args.vm_id,
                vm_ip=args.vm_ip,
                container_id=args.container_id,
                model_name=args.model_name,
                inputs=inputs,
                allow_transient=bool(args.allow_transient),
            )

            resp = await client._send(infer_msg)  # type: ignore[attr-defined]

            # 1) System-level errors (e.g. shutdown draining)
            if resp.get("type") == "error":
                code = (resp.get("payload") or {}).get("code")
                if code == "SYSTEM_SHUTDOWN":
                    # Stop-the-world: reconnect only after readiness.
                    await client.__aexit__(None, None, None)
                    client = None

                    sleep_s = policy.backoff(attempt)
                    await asyncio.sleep(sleep_s)

                    ready, error_id, detail = _ready_check(args.manager_http_base)
                    if not ready:
                        # Keep backing off until manager is ready again.
                        # error_id is what SREs use to correlate server logs.
                        print(
                            json.dumps(
                                {
                                    "event": "manager_not_ready",
                                    "attempt": attempt,
                                    "error_id": error_id,
                                    "detail": detail,
                                },
                                indent=2,
                            )
                        )
                        continue
                    continue

                raise RuntimeError(f"Non-retriable system error: {resp}")

            # 2) Inference failures: structured Triton-facing payload
            typed = _extract_typed_triton_error(resp)
            if typed is None:
                # COMPLETED or non-typed contract errors (string). Treat as terminal success/error.
                print(json.dumps({"attempt": attempt, "response": resp}, indent=2))
                return

            code = str(typed.get("code") or "UNKNOWN")
            retriable = bool(typed.get("retriable"))
            retry_after = typed.get("retry_after_seconds")
            retry_hint = float(retry_after) if isinstance(retry_after, (int, float)) else None

            if code == "TRITON_TIMEOUT" and retriable:
                sleep_s = policy.backoff(attempt, server_hint_seconds=retry_hint)
                print(json.dumps({"event": "retry_triton_timeout", "attempt": attempt, "sleep_s": sleep_s}, indent=2))
                await asyncio.sleep(sleep_s)
                continue

            if retriable:
                sleep_s = policy.backoff(attempt, server_hint_seconds=retry_hint)
                print(json.dumps({"event": "retry_retriable_error", "code": code, "attempt": attempt}, indent=2))
                await asyncio.sleep(sleep_s)
                continue

            # Fatal errors: do not retry.
            print(json.dumps({"event": "fatal_inference_error", "attempt": attempt, "error": typed}, indent=2))
            return

        except Exception as exc:
            # Network hiccups / socket issues: treat as retriable transport errors, reconnect with backoff.
            if client is not None:
                try:
                    await client.__aexit__(None, None, None)
                except Exception:
                    pass
                client = None

            sleep_s = policy.backoff(attempt)
            print(
                json.dumps(
                    {
                        "event": "transport_retry",
                        "attempt": attempt,
                        "sleep_s": sleep_s,
                        "error": str(exc),
                    },
                    indent=2,
                )
            )
            await asyncio.sleep(sleep_s)
            continue

    raise SystemExit(f"Exceeded max attempts ({policy.max_attempts}).")


def main() -> None:
    started = time.time()
    try:
        asyncio.run(orchestrate_with_retries())
    finally:
        elapsed = time.time() - started
        print(json.dumps({"elapsed_s": elapsed}, indent=2))


if __name__ == "__main__":
    main()
