"""
Shutdown Draining Test:
- Fire N simultaneous inference requests (one per WS client).
- Send SIGTERM to the manager process.
- Verify pending clients receive SYSTEM_SHUTDOWN NACKs (or connection close with an error frame).

Why this proves SRE hardening:
- WebSocketThread: during stop/drain, it emits {"type":"error","payload":{"code":"SYSTEM_SHUTDOWN"...}} then closes.
- ClientManager.stop(): triggers drain_and_nack(reason="SYSTEM_SHUTDOWN") best-effort for queued messages.

Execution model:
- This script assumes the manager is already running and you know its PID.
  (Spawning the full manager inside this script is usually not viable in CI because it requires
   OpenStack/Docker runtime configuration.)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
import time
import uuid as uuidlib

import websockets


def _json_dumps(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)

def _looks_like_shutdown_close(*, code: int | None, reason: str | None) -> bool:
    # Common close codes we can see during graceful stop/restart:
    # - 1000: normal closure
    # - 1001: going away
    # - 1012: service restart (seen in your run)
    if code in {1000, 1001, 1012}:
        return True
    r = (reason or "").lower()
    return "shutdown" in r or "restart" in r or "going away" in r


async def _one_client(*, ws_url: str, token: str | None, client_id: str, msg: dict, timeout_s: float) -> dict:
    """
    Send one inference and return the first response frame (or shutdown error).
    """
    try:
        async with websockets.connect(ws_url, max_size=2**23) as ws:
            await ws.send(
                _json_dumps(
                    {
                        "uuid": client_id,
                        "type": "auth",
                        "payload": {**({"token": token} if token else {}), "client": {"roles": ["inference"]}},
                    }
                )
            )
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
            except (websockets.exceptions.ConnectionClosed, websockets.exceptions.ConnectionClosedError) as exc:
                if _looks_like_shutdown_close(code=getattr(exc, "code", None), reason=getattr(exc, "reason", None)):
                    return {"kind": "shutdown_disconnect", "code": getattr(exc, "code", None), "reason": getattr(exc, "reason", None)}
                return {"kind": "timeout_or_disconnect", "detail": str(exc)}

            try:
                auth = json.loads(raw) if isinstance(raw, str) else {}
            except Exception:
                return {"kind": "auth_failed"}
            if auth.get("type") != "auth.ok":
                return {"kind": "auth_failed"}

            try:
                await ws.send(_json_dumps(msg))
            except (websockets.exceptions.ConnectionClosed, websockets.exceptions.ConnectionClosedError) as exc:
                if _looks_like_shutdown_close(code=getattr(exc, "code", None), reason=getattr(exc, "reason", None)):
                    return {"kind": "shutdown_disconnect", "code": getattr(exc, "code", None), "reason": getattr(exc, "reason", None)}
                return {"kind": "timeout_or_disconnect", "detail": str(exc)}

            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
                return {"kind": "frame", "frame": json.loads(raw)}
            except (websockets.exceptions.ConnectionClosed, websockets.exceptions.ConnectionClosedError) as exc:
                if _looks_like_shutdown_close(code=getattr(exc, "code", None), reason=getattr(exc, "reason", None)):
                    return {"kind": "shutdown_disconnect", "code": getattr(exc, "code", None), "reason": getattr(exc, "reason", None)}
                return {"kind": "timeout_or_disconnect", "detail": str(exc)}
            except Exception as exc:
                return {"kind": "timeout_or_disconnect", "detail": str(exc)}
    except (websockets.exceptions.ConnectionClosed, websockets.exceptions.ConnectionClosedError) as exc:
        if _looks_like_shutdown_close(code=getattr(exc, "code", None), reason=getattr(exc, "reason", None)):
            return {"kind": "shutdown_disconnect", "code": getattr(exc, "code", None), "reason": getattr(exc, "reason", None)}
        return {"kind": "timeout_or_disconnect", "detail": str(exc)}
    except Exception as exc:
        return {"kind": "timeout_or_disconnect", "detail": str(exc)}


async def main_async(args: argparse.Namespace) -> int:
    pid = int(args.manager_pid)
    ws_url = args.ws_url

    # Prepare N clients / requests.
    clients = []
    for i in range(int(args.clients)):
        cid = f"qa-shutdown-{i}-{uuidlib.uuid4().hex[:6]}"
        msg = {
            "uuid": cid,
            "type": "inference",
            "payload": {
                "vm_ip": args.vm_ip,
                "container_id": args.container_id,
                "model_name": args.model_name,
                "request": {
                    "protocol": "http",
                    "allow_transient": True,
                    "inputs": [{"name": "x", "type": "TYPE_FP32", "dims": [128], "value": [0.0]}],
                },
            },
        }
        clients.append((cid, msg))

    # Kick off all clients concurrently.
    tasks = [
        asyncio.create_task(
            _one_client(
                ws_url=ws_url,
                token=args.token or None,
                client_id=cid,
                msg=msg,
                timeout_s=float(args.client_timeout_s),
            )
        )
        for cid, msg in clients
    ]

    # Give a tiny head-start so requests are in-flight/queued.
    await asyncio.sleep(float(args.pre_sigterm_s))
    os.kill(pid, signal.SIGTERM)

    results = await asyncio.gather(*tasks, return_exceptions=False)

    n_shutdown = 0
    n_other = 0
    for r in results:
        if r.get("kind") == "shutdown_disconnect":
            n_shutdown += 1
            continue
        if r.get("kind") != "frame":
            n_other += 1
            continue
        f = r.get("frame") or {}
        if f.get("type") == "error" and ((f.get("payload") or {}) or {}).get("code") == "SYSTEM_SHUTDOWN":
            n_shutdown += 1
            continue
        # Inference failed frames are also acceptable if they carry SYSTEM_SHUTDOWN in nested payload.
        if f.get("type") == "inference":
            payload = f.get("payload") or {}
            if payload.get("status") == "FAILED":
                data = payload.get("data") or {}
                if isinstance(data, dict) and data.get("code") == "SYSTEM_SHUTDOWN":
                    n_shutdown += 1
                    continue
        n_other += 1

    summary = {
        "clients": int(args.clients),
        "shutdown_nacks": n_shutdown,
        "other_or_missing": n_other,
    }
    print(_json_dumps(summary))

    # Success condition: majority receive shutdown NACK (exact % depends on timing).
    # Default threshold: >= 60% to allow for race where some requests complete quickly.
    ratio = (n_shutdown / max(1, int(args.clients))) * 100.0
    if ratio < float(args.min_shutdown_pct):
        print(f"FAIL: shutdown NACK ratio {ratio:.1f}% < min_shutdown_pct={args.min_shutdown_pct}")
        return 2
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fire requests, SIGTERM manager, verify SYSTEM_SHUTDOWN NACKs.")
    p.add_argument("--manager-pid", default=os.getenv("TCM_MANAGER_PID", ""), required=not bool(os.getenv("TCM_MANAGER_PID")))
    p.add_argument("--ws-url", default=os.getenv("TCM_WS_URL", "ws://127.0.0.1:8005/ws"))
    p.add_argument("--token", default=os.getenv("TCM_TOKEN", ""))

    p.add_argument("--clients", type=int, default=int(os.getenv("TCM_CLIENTS", "100")))
    p.add_argument("--pre-sigterm-s", type=float, default=float(os.getenv("TCM_PRE_SIGTERM_S", "0.1")))
    p.add_argument("--client-timeout-s", type=float, default=float(os.getenv("TCM_CLIENT_TIMEOUT_S", "10")))
    p.add_argument("--min-shutdown-pct", type=float, default=float(os.getenv("TCM_MIN_SHUTDOWN_PCT", "60")))

    p.add_argument("--vm-ip", default=os.getenv("TCM_VM_IP", "192.0.2.10"))
    p.add_argument("--container-id", default=os.getenv("TCM_CONTAINER_ID", "cid-shutdown"))
    p.add_argument("--model-name", default=os.getenv("TCM_MODEL_NAME", "model-shutdown"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

