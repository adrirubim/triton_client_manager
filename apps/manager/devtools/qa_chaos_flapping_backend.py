"""
Chaos Scenario A: "The Flapping Backend"

What we can prove without adding new features:
- /ready is safe under high-frequency polling (O(1) within the 1s readiness TTL cache window).
- The manager does not collapse when backend reachability is unstable:
  - Keep WS load + /ready storm in parallel.
  - Optionally point inference at an unreachable Triton endpoint to exercise retriable normalization.

This script focuses on measuring:
- /ready latency distribution (with emphasis on sub-1s repeated calls).
- Status stability (503/200 frequency) under load.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import random
import statistics
import time
import uuid as uuidlib

import httpx
import websockets


def _json_dumps(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


async def _ws_worker(
    *,
    ws_url: str,
    token: str | None,
    roles: list[str],
    vm_ip: str,
    container_id: str,
    model_name: str,
    stop: asyncio.Event,
) -> None:
    cid = f"qa-flap-{uuidlib.uuid4().hex[:10]}"
    try:
        async with websockets.connect(ws_url, max_size=2**23) as ws:
            await ws.send(
                _json_dumps(
                    {
                        "uuid": cid,
                        "type": "auth",
                        "payload": {**({"token": token} if token else {}), "client": {"roles": roles}},
                    }
                )
            )
            raw = await ws.recv()
            if (json.loads(raw) if isinstance(raw, str) else {}).get("type") != "auth.ok":
                return

            while not stop.is_set():
                # Keep the manager busy with inference attempts. It's okay if backend isn't present:
                # the goal is to keep exercising the pipeline under "unhealthy backend" turbulence.
                await ws.send(
                    _json_dumps(
                        {
                            "uuid": cid,
                            "type": "inference",
                            "payload": {
                                "vm_ip": vm_ip,
                                "container_id": container_id,
                                "model_name": model_name,
                                "request": {
                                    "protocol": "http",
                                    "allow_transient": True,
                                    "inputs": [{"name": "x", "type": "TYPE_FP32", "dims": [128], "value": [0.0]}],
                                },
                            },
                        }
                    )
                )
                # Consume one response (COMPLETED/FAILED/error); discard content.
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(ws.recv(), timeout=5.0)
                await asyncio.sleep(0.01)
    except Exception:
        return


async def _poll_ready(*, http_base: str, qps: float, seconds: float) -> dict:
    url = http_base.rstrip("/") + "/ready"
    lat_ms: list[float] = []
    codes: list[int] = []

    interval = 1.0 / float(max(1e-6, qps))
    end = time.perf_counter() + float(seconds)

    async with httpx.AsyncClient(timeout=2.0) as client:
        while time.perf_counter() < end:
            t0 = time.perf_counter()
            try:
                r = await client.get(url)
                codes.append(int(r.status_code))
            except Exception:
                codes.append(0)
            lat_ms.append((time.perf_counter() - t0) * 1000.0)
            await asyncio.sleep(interval)

    def _pct(p: float) -> float:
        if not lat_ms:
            return 0.0
        xs = sorted(lat_ms)
        k = int(round((p / 100.0) * (len(xs) - 1)))
        return float(xs[max(0, min(len(xs) - 1, k))])

    return {
        "samples": len(lat_ms),
        "status_code_counts": {str(c): codes.count(c) for c in sorted(set(codes))},
        "latency_ms": {
            "min": min(lat_ms) if lat_ms else 0.0,
            "p50": _pct(50),
            "p90": _pct(90),
            "p99": _pct(99),
            "max": max(lat_ms) if lat_ms else 0.0,
            "mean": statistics.mean(lat_ms) if lat_ms else 0.0,
        },
    }


async def main_async(args: argparse.Namespace) -> int:
    random.seed(args.seed)
    stop = asyncio.Event()

    # Background WS turbulence (optional)
    ws_tasks = []
    if args.ws_workers > 0:
        for _ in range(int(args.ws_workers)):
            ws_tasks.append(
                asyncio.create_task(
                    _ws_worker(
                        ws_url=args.ws_url,
                        token=args.token or None,
                        roles=args.roles,
                        vm_ip=args.vm_ip,
                        container_id=args.container_id,
                        model_name=args.model_name,
                        stop=stop,
                    )
                )
            )

    # /ready storm
    res = await _poll_ready(http_base=args.http_base, qps=float(args.ready_qps), seconds=float(args.seconds))

    stop.set()
    if ws_tasks:
        await asyncio.gather(*ws_tasks, return_exceptions=True)

    print(_json_dumps(res))

    # Hard expectations for the 1s TTL cache:
    # - Under high QPS, p99 should remain low (no full I/O check per request).
    # Pick a pragmatic budget; tune per environment.
    p99 = float(((res.get("latency_ms") or {}) or {}).get("p99") or 0.0)
    if p99 > float(args.max_p99_ms):
        print(f"FAIL: /ready p99={p99:.2f}ms exceeds max_p99_ms={args.max_p99_ms}")
        return 2
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Chaos A: Flapping backend via /ready storm + WS turbulence.")
    p.add_argument("--http-base", default=os.getenv("TCM_HTTP_BASE", "http://127.0.0.1:8005"))
    p.add_argument("--ws-url", default=os.getenv("TCM_WS_URL", "ws://127.0.0.1:8005/ws"))
    p.add_argument("--seconds", type=float, default=float(os.getenv("TCM_SECONDS", "15")))
    p.add_argument("--ready-qps", type=float, default=float(os.getenv("TCM_READY_QPS", "200")))
    p.add_argument("--max-p99-ms", type=float, default=float(os.getenv("TCM_READY_P99_MS", "25")))
    p.add_argument("--seed", type=int, default=int(os.getenv("TCM_SEED", "1337")))

    p.add_argument("--ws-workers", type=int, default=int(os.getenv("TCM_WS_WORKERS", "50")))
    p.add_argument("--token", default=os.getenv("TCM_TOKEN", ""))
    p.add_argument("--roles", nargs="+", default=["inference"])

    # Inference target (optional turbulence only)
    p.add_argument("--vm-ip", default=os.getenv("TCM_VM_IP", "192.0.2.10"))
    p.add_argument("--container-id", default=os.getenv("TCM_CONTAINER_ID", "cid-flap"))
    p.add_argument("--model-name", default=os.getenv("TCM_MODEL_NAME", "model-flap"))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
