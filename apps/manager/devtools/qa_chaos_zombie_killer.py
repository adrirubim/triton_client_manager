"""
Chaos Scenario B: "The Zombie Killer"

Test idea:
- Start a gRPC streaming inference (protocol="grpc") over the WebSocket.
- As soon as we see "START", abruptly close the WebSocket.
- Verify stream cancellation happened by checking metrics:
  - tcm_grpc_stream_failures_total{reason="client_cancel"} increases.

This validates:
- WebSocket disconnect triggers cancel event for in-flight stream work.
- TritonInfer.stream checks cancel_event quickly (polling loop) and aborts backend work.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid as uuidlib

import httpx
import websockets


def _json_dumps(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


async def _get_metrics_text(http_base: str) -> str:
    url = http_base.rstrip("/") + "/metrics"
    async with httpx.AsyncClient(timeout=2.0) as client:
        r = await client.get(url)
        r.raise_for_status()
        return str(r.text or "")


def _extract_counter(metrics_text: str, *, metric: str, match: str) -> float:
    """
    Extremely small parser for Prometheus text format:
    finds lines like: metric{...} 123
    and sums values that contain the 'match' substring.
    """
    total = 0.0
    for line in (metrics_text or "").splitlines():
        if not line or line.startswith("#"):
            continue
        if not line.startswith(metric):
            continue
        if match not in line:
            continue
        try:
            total += float(line.strip().split()[-1])
        except Exception:
            continue
    return float(total)


async def main_async(args: argparse.Namespace) -> int:
    before = await _get_metrics_text(args.http_base)
    b = _extract_counter(before, metric="tcm_grpc_stream_failures_total", match='reason="client_cancel"')

    client_id = f"qa-zombie-{uuidlib.uuid4().hex[:10]}"
    async with websockets.connect(args.ws_url, max_size=2**23) as ws:
        await ws.send(
            _json_dumps(
                {
                    "uuid": client_id,
                    "type": "auth",
                    "payload": {**({"token": args.token} if args.token else {}), "client": {"roles": ["inference"]}},
                }
            )
        )
        raw = await asyncio.wait_for(ws.recv(), timeout=args.timeout_s)
        if (json.loads(raw) if isinstance(raw, str) else {}).get("type") != "auth.ok":
            print("FAIL: auth did not succeed")
            return 2

        # Send a streaming inference. This requires a real gRPC streaming-capable model.
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
                            "protocol": "grpc",
                            "allow_transient": True,
                            "output_name": args.output_name,
                            "inputs": [{"name": "x", "type": "TYPE_FP32", "dims": [1], "value": [0.0]}],
                        },
                    },
                }
            )
        )

        # Wait for START (or FAILED) then hard-close the socket.
        t_end = time.perf_counter() + float(args.timeout_s)
        saw_start = False
        while time.perf_counter() < t_end:
            raw = await asyncio.wait_for(ws.recv(), timeout=args.timeout_s)
            msg = json.loads(raw)
            if msg.get("type") == "inference":
                st = ((msg.get("payload") or {}) or {}).get("status")
                if st == "START":
                    saw_start = True
                    break
                if st == "FAILED":
                    print(_json_dumps({"note": "stream_failed_before_start", "msg": msg}))
                    break
            if msg.get("type") == "error":
                print(_json_dumps({"note": "ws_error", "msg": msg}))
                break

        # Abrupt close (no graceful drain).
        await ws.close()
        if not saw_start:
            print("WARN: did not observe START; metrics delta may be 0 if stream never started.")

    # Give the manager a moment to record the cancellation failure metric.
    await asyncio.sleep(float(args.post_wait_s))
    after = await _get_metrics_text(args.http_base)
    a = _extract_counter(after, metric="tcm_grpc_stream_failures_total", match='reason="client_cancel"')
    delta = a - b

    print(
        _json_dumps(
            {
                "grpc_stream_client_cancel_before": b,
                "grpc_stream_client_cancel_after": a,
                "delta": delta,
            }
        )
    )

    if delta < 1:
        print("FAIL: expected tcm_grpc_stream_failures_total{reason=\"client_cancel\"} to increase.")
        return 2
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chaos B: Zombie Killer (disconnect cancels gRPC stream).")
    p.add_argument("--http-base", default=os.getenv("TCM_HTTP_BASE", "http://127.0.0.1:8005"))
    p.add_argument("--ws-url", default=os.getenv("TCM_WS_URL", "ws://127.0.0.1:8005/ws"))
    p.add_argument("--token", default=os.getenv("TCM_TOKEN", ""))
    p.add_argument("--timeout-s", type=float, default=float(os.getenv("TCM_TIMEOUT_S", "10")))
    p.add_argument("--post-wait-s", type=float, default=float(os.getenv("TCM_POST_WAIT_S", "0.5")))

    p.add_argument("--vm-ip", default=os.getenv("TCM_VM_IP", "127.0.0.1"))
    p.add_argument("--container-id", default=os.getenv("TCM_CONTAINER_ID", "cid-zombie"))
    p.add_argument("--model-name", default=os.getenv("TCM_MODEL_NAME", "model-zombie"))
    p.add_argument("--output-name", default=os.getenv("TCM_OUTPUT_NAME", "output"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

