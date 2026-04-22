"""
Chaos Scenario C: "Timeout Stress"

Goal:
- Force an HTTP inference to exceed network_timeout and verify the manager
  returns a typed, retriable timeout error:
    payload.data.code == "TRITON_TIMEOUT"
    payload.data.retriable == true

How we force the delay (no new features required):
- Run a local "blackhole" HTTP server on 127.0.0.1:8000 that accepts connections
  but never responds. Then send allow_transient HTTP inference to vm_ip=127.0.0.1.

Prereqs:
- The manager must run on the same host where this blackhole binds (so its
  Triton HTTP client hits localhost:8000).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import socket
import time
import uuid as uuidlib

import websockets


def _json_dumps(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


async def _blackhole_http_server(host: str, port: int, stop: asyncio.Event) -> None:
    """
    Accept TCP connections and never reply (simulates a hung upstream).
    """

    async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            # Read a bit to complete HTTP request arrival, then stall.
            with contextlib.suppress(Exception):
                await reader.read(1024)
            await stop.wait()
        finally:
            with contextlib.suppress(Exception):
                writer.close()
                await writer.wait_closed()

    server = await asyncio.start_server(_handle, host=host, port=port, reuse_address=True)
    async with server:
        await stop.wait()


async def main_async(args: argparse.Namespace) -> int:
    stop = asyncio.Event()

    # Best-effort pre-bind check to give a crisp failure if port is in use.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((args.blackhole_host, int(args.blackhole_port)))
    except OSError as exc:
        print(_json_dumps({"error": "blackhole_bind_failed", "detail": str(exc)}))
        return 2
    finally:
        s.close()

    bh_task = asyncio.create_task(_blackhole_http_server(args.blackhole_host, int(args.blackhole_port), stop))
    await asyncio.sleep(0.1)

    client_id = f"qa-timeout-{uuidlib.uuid4().hex[:10]}"
    try:
        async with websockets.connect(args.ws_url, max_size=2**23) as ws:
            await ws.send(
                _json_dumps(
                    {
                        "uuid": client_id,
                        "type": "auth",
                        "payload": {
                            **({"token": args.token} if args.token else {}),
                            "client": {"roles": ["inference"]},
                        },
                    }
                )
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=args.timeout_s)
            if (json.loads(raw) if isinstance(raw, str) else {}).get("type") != "auth.ok":
                print("FAIL: auth did not succeed")
                return 2

            t0 = time.perf_counter()
            await ws.send(
                _json_dumps(
                    {
                        "uuid": client_id,
                        "type": "inference",
                        "payload": {
                            "vm_ip": args.vm_ip,
                            "container_id": args.container_id,
                            "model_name": args.model_name,
                            "request": {
                                "protocol": "http",
                                "allow_transient": True,
                                "inputs": [{"name": "x", "type": "TYPE_FP32", "dims": [1], "value": [0.0]}],
                            },
                        },
                    }
                )
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=float(args.wait_for_response_s))
            dt = time.perf_counter() - t0
            msg = json.loads(raw)
            print(_json_dumps({"elapsed_s": round(dt, 3), "response": msg}))

            if msg.get("type") != "inference":
                print("FAIL: expected inference response")
                return 2

            payload = msg.get("payload") or {}
            if payload.get("status") != "FAILED":
                print("FAIL: expected FAILED due to timeout")
                return 2

            data = payload.get("data") or {}
            if not isinstance(data, dict):
                print("FAIL: expected structured error dict in payload.data")
                return 2

            if data.get("code") != "TRITON_TIMEOUT" or str(data.get("retriable")).lower() != "true":
                print("FAIL: expected TRITON_TIMEOUT retriable=true")
                return 2
            return 0
    finally:
        stop.set()
        with contextlib.suppress(Exception):
            await bh_task


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chaos C: Force timeout and validate TRITON_TIMEOUT handling.")
    p.add_argument("--ws-url", default=os.getenv("TCM_WS_URL", "ws://127.0.0.1:8005/ws"))
    p.add_argument("--token", default=os.getenv("TCM_TOKEN", ""))
    p.add_argument("--timeout-s", type=float, default=float(os.getenv("TCM_TIMEOUT_S", "10")))
    p.add_argument("--wait-for-response-s", type=float, default=float(os.getenv("TCM_WAIT_FOR_RESPONSE_S", "90")))

    # Target Triton endpoint as seen by the manager.
    # Default: localhost to hit the blackhole.
    p.add_argument("--vm-ip", default=os.getenv("TCM_VM_IP", "127.0.0.1"))
    p.add_argument("--container-id", default=os.getenv("TCM_CONTAINER_ID", "cid-timeout"))
    p.add_argument("--model-name", default=os.getenv("TCM_MODEL_NAME", "model-timeout"))

    # Blackhole bind (must match manager's Triton HTTP port).
    p.add_argument("--blackhole-host", default=os.getenv("TCM_BLACKHOLE_HOST", "127.0.0.1"))
    p.add_argument("--blackhole-port", type=int, default=int(os.getenv("TCM_BLACKHOLE_PORT", "8000")))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
