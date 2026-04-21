"""
High-Concurrency WebSocket load tester for triton_client_manager.

Goals:
- Simulate 1,000+ concurrent WS clients.
- Send inference requests and validate:
  - Oversized payloads trigger "413 Payload Too Large" (manager-side admission control).
  - System remains responsive under load (no event loop collapse).

Notes:
- This tool speaks the manager's WS protocol:
  - First message MUST be type "auth" with matching uuid.
  - Subsequent messages can be "inference" with payload.
- Payload budget enforcement is based on an estimate from input dims/datatype, not raw values.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time
import uuid as uuidlib
from dataclasses import dataclass

import websockets


def _now() -> float:
    return time.perf_counter()


def _json_dumps(obj: object) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def _input_under_budget(*, max_mb: int) -> list[dict]:
    # Keep estimate safely under the limit.
    # FP32 -> 4 bytes/elem. Use ~25% of budget.
    if max_mb <= 0:
        n = 128
    else:
        limit_bytes = max_mb * 1024 * 1024
        n = max(1, int(limit_bytes * 0.25 // 4))
    return [
        {
            "name": "x",
            "type": "TYPE_FP32",
            "dims": [n],
            "value": [0.0],  # value content isn't used for budget enforcement
        }
    ]


def _input_over_budget(*, max_mb: int) -> list[dict]:
    # Force estimate just above the limit.
    # FP32 -> 4 bytes/elem.
    if max_mb <= 0:
        # If budget isn't enabled, still generate something large-ish.
        n = 100 * 1024 * 1024 // 4 + 1
    else:
        limit_bytes = max_mb * 1024 * 1024
        n = int(limit_bytes // 4) + 1
    return [
        {
            "name": "x",
            "type": "TYPE_FP32",
            "dims": [n],
            "value": [0.0],
        }
    ]


@dataclass
class Counters:
    ok: int = 0
    completed: int = 0
    failed: int = 0
    payload_413: int = 0
    system_shutdown: int = 0
    other_errors: int = 0
    connect_errors: int = 0
    inference_timeouts: int = 0
    # Debug aids (best-effort): capture a few representative FAILED messages.
    failed_messages: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.failed_messages is None:
            self.failed_messages = []

    def note_failed_message(self, msg: str) -> None:
        m = str(msg or "").strip()
        if not m:
            return
        # Keep a small sample set to avoid noisy output.
        if m in self.failed_messages:
            return
        if len(self.failed_messages) >= 5:
            return
        self.failed_messages.append(m)


async def _ws_client(
    *,
    ws_url: str,
    client_id: str,
    token: str | None,
    roles: list[str],
    vm_ip: str,
    container_id: str,
    model_name: str,
    max_mb: int,
    oversize_ratio: float,
    requests: int,
    think_ms: int,
    counters: Counters,
    timeout_s: float,
    allow_transient: bool,
) -> None:
    try:
        async with websockets.connect(ws_url, max_size=2**23) as ws:
            # --- auth ---
            await ws.send(
                _json_dumps(
                    {
                        "uuid": client_id,
                        "type": "auth",
                        "payload": {
                            **({"token": token} if token else {}),
                            "client": {"roles": roles},
                        },
                    }
                )
            )
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
            try:
                msg = json.loads(raw)
            except Exception:
                msg = {"type": raw}
            if msg.get("type") != "auth.ok":
                counters.connect_errors += 1
                return

            counters.ok += 1

            # --- workload ---
            for _ in range(int(max(0, requests))):
                oversized = random.random() < float(oversize_ratio)
                inputs = _input_over_budget(max_mb=max_mb) if oversized else _input_under_budget(max_mb=max_mb)
                req = {
                    "uuid": client_id,
                    "type": "inference",
                    "payload": {
                        "vm_ip": vm_ip,
                        "container_id": container_id,
                        "model_name": model_name,
                        "request": {
                            "protocol": "http",
                            "allow_transient": bool(allow_transient),
                            "inputs": inputs,
                        },
                    },
                }
                await ws.send(_json_dumps(req))

                # Expect one inference response (COMPLETED or FAILED) for HTTP single-shot.
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=timeout_s)
                except asyncio.TimeoutError:
                    counters.inference_timeouts += 1
                    return
                try:
                    resp = json.loads(raw)
                except Exception:
                    counters.other_errors += 1
                    continue

                # Server may emit shutdown errors mid-test.
                if resp.get("type") == "error":
                    code = ((resp.get("payload") or {}) or {}).get("code")
                    if code == "SYSTEM_SHUTDOWN":
                        counters.system_shutdown += 1
                        return
                    counters.other_errors += 1
                    continue

                if resp.get("type") != "inference":
                    counters.other_errors += 1
                    continue

                payload = resp.get("payload") or {}
                status = payload.get("status")
                data = payload.get("data")
                if status == "COMPLETED":
                    counters.completed += 1
                elif status == "FAILED":
                    counters.failed += 1
                    msg = ""
                    if isinstance(data, dict):
                        msg = str(data.get("message") or "")
                    else:
                        msg = str(data or "")
                    counters.note_failed_message(msg)
                    if "413 Payload Too Large" in msg:
                        counters.payload_413 += 1
                else:
                    counters.other_errors += 1

                if think_ms > 0:
                    await asyncio.sleep(float(think_ms) / 1000.0)
    except Exception:
        counters.connect_errors += 1


async def main_async(args: argparse.Namespace) -> int:
    random.seed(args.seed)
    ws_url = args.ws_url

    counters = Counters()
    sem = asyncio.Semaphore(int(args.max_inflight_connects))
    start = _now()

    async def _run_one(i: int) -> None:
        async with sem:
            cid = f"{args.client_prefix}{i}-{uuidlib.uuid4().hex[:8]}"
            await _ws_client(
                ws_url=ws_url,
                client_id=cid,
                token=args.token or None,
                roles=args.roles,
                vm_ip=args.vm_ip,
                container_id=args.container_id,
                model_name=args.model_name,
                max_mb=int(args.max_request_payload_mb),
                oversize_ratio=float(args.oversize_ratio),
                requests=int(args.requests_per_client),
                think_ms=int(args.think_ms),
                counters=counters,
                timeout_s=float(args.timeout_s),
                allow_transient=bool(args.allow_transient),
            )

    tasks = [asyncio.create_task(_run_one(i)) for i in range(int(args.clients))]
    await asyncio.gather(*tasks)

    dur = _now() - start
    total_reqs = int(args.clients) * int(args.requests_per_client)
    print(_json_dumps({"duration_s": round(dur, 3), "total_requests_planned": total_reqs}))
    # Print counters without the potentially noisy message samples first.
    summary = dict(counters.__dict__)
    failed_samples = list(summary.pop("failed_messages", []) or [])
    print(_json_dumps(summary))

    # Invariants: every planned request should yield a WS response in healthy runs.
    # (Allow SYSTEM_SHUTDOWN short-circuit when explicitly testing shutdown.)
    if counters.connect_errors > 0 or counters.inference_timeouts > 0:
        print("FAIL: connection/timeouts detected during load test.")
        return 2
    # Count any received response (including error/protocol messages) as "a response".
    if (counters.completed + counters.failed + counters.system_shutdown + counters.other_errors) != total_reqs:
        print("FAIL: did not receive one response per request.")
        return 2

    # Basic invariants for admission control verification
    if float(args.oversize_ratio) > 0 and int(args.max_request_payload_mb) > 0:
        if counters.payload_413 == 0:
            if failed_samples:
                print("DEBUG: sample FAILED message(s) seen (first 5 unique):")
                for s in failed_samples[:5]:
                    print(f"- {s}")
            print("FAIL: expected at least one 413 Payload Too Large response.")
            return 2
    return 0


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="High-concurrency WS load tester (inference + 413 budget checks).")
    p.add_argument("--ws-url", default=os.getenv("TCM_WS_URL", "ws://127.0.0.1:8005/ws"))
    p.add_argument("--clients", type=int, default=int(os.getenv("TCM_CLIENTS", "1000")))
    p.add_argument("--requests-per-client", type=int, default=int(os.getenv("TCM_REQUESTS_PER_CLIENT", "1")))
    p.add_argument("--max-inflight-connects", type=int, default=int(os.getenv("TCM_MAX_INFLIGHT_CONNECTS", "250")))
    p.add_argument("--timeout-s", type=float, default=float(os.getenv("TCM_TIMEOUT_S", "10")))
    p.add_argument("--think-ms", type=int, default=int(os.getenv("TCM_THINK_MS", "0")))
    p.add_argument("--seed", type=int, default=int(os.getenv("TCM_SEED", "1337")))

    # Auth
    p.add_argument("--token", default=os.getenv("TCM_TOKEN", ""))
    p.add_argument("--roles", nargs="+", default=["inference"])
    p.add_argument("--client-prefix", default=os.getenv("TCM_CLIENT_PREFIX", "qa-"))

    # Inference target (fields are required even when failing fast on payload budget)
    p.add_argument("--vm-ip", default=os.getenv("TCM_VM_IP", "127.0.0.1"))
    p.add_argument("--container-id", default=os.getenv("TCM_CONTAINER_ID", "cid-qa"))
    p.add_argument("--model-name", default=os.getenv("TCM_MODEL_NAME", "model-qa"))
    # WARNING: Triton HTTP_PORT defaults to 8000. In local/dev setups, that's often the manager itself,
    # so transient inference can self-call and hang. Keep this OFF by default.
    p.add_argument("--allow-transient", action="store_true", default=False)

    # Payload budget checks
    # Default 0 to match repo config (admission control disabled unless explicitly enabled).
    p.add_argument("--max-request-payload-mb", type=int, default=int(os.getenv("TCM_MAX_REQUEST_PAYLOAD_MB", "0")))
    p.add_argument("--oversize-ratio", type=float, default=float(os.getenv("TCM_OVERSIZE_RATIO", "0.3")))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    raise SystemExit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()

