from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from typing import List, Optional

from .sdk import AuthContext, InferenceInput, TcmWebSocketClient
from .model_analyze import AnalyzeModelAction


def _parse_roles(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [r.strip() for r in raw.split(",") if r.strip()]


async def _run_queue_stats(
    uri: str, ctx: AuthContext, repeat: int, concurrency: int
) -> None:
    """
    Run one or more `info.queue_stats` calls.

    - If repeat == 1 and concurrency == 1: acts as a simple smoke check.
    - Otherwise: runs a small load test, printing basic latency statistics.
    """

    async def one_call(suffix: str | None = None) -> float:
        start = time.perf_counter()
        # For concurrent runs we need unique UUIDs per connection to avoid
        # "UUID '...' is already connected" errors from the server.
        if suffix:
            derived = AuthContext(
                uuid=f"{ctx.uuid}-{suffix}",
                token=ctx.token,
                sub=ctx.sub or ctx.uuid,
                tenant_id=ctx.tenant_id,
                roles=ctx.roles,
            )
        else:
            derived = ctx

        async with TcmWebSocketClient(uri, derived) as client:
            await client.auth()
            resp = await client.info_queue_stats()
        elapsed = time.perf_counter() - start
        print(json.dumps(resp, indent=2))
        return elapsed

    if repeat == 1 and concurrency == 1:
        await one_call()
        return

    latencies: List[float] = []

    async def worker(worker_id: int, n: int) -> None:
        for i in range(n):
            suffix = f"w{worker_id}-n{i}"
            latencies.append(await one_call(suffix=suffix))

    per_worker = repeat // concurrency
    extra = repeat % concurrency
    tasks = []
    for i in range(concurrency):
        n = per_worker + (1 if i < extra else 0)
        if n:
            tasks.append(asyncio.create_task(worker(i, n)))

    await asyncio.gather(*tasks)

    if not latencies:
        return

    latencies.sort()
    total = sum(latencies)
    avg = total / len(latencies)
    p50 = latencies[int(0.5 * (len(latencies) - 1))]
    p95 = latencies[int(0.95 * (len(latencies) - 1))]
    p99 = latencies[int(0.99 * (len(latencies) - 1))]

    summary = {
        "requests": len(latencies),
        "concurrency": concurrency,
        "latency_seconds": {
            "avg": avg,
            "p50": p50,
            "p95": p95,
            "p99": p99,
        },
    }
    print(json.dumps({"queue_stats_summary": summary}, indent=2))


async def _run_management_creation(
    uri: str,
    ctx: AuthContext,
    action: str,
    payload_path: Optional[str],
) -> None:
    """
    Run a single management.creation/deletion-style call using a JSON payload.

    The payload file must contain the `payload` body that will be merged under
    `payload` in the WebSocket message (e.g. fields like `openstack`, `docker`,
    `minio`, `vm_id`, `container_id`, etc.), not the full envelope.
    """

    body: dict = {}
    if payload_path:
        with open(payload_path, "r", encoding="utf-8") as f:
            body = json.load(f)

    async with TcmWebSocketClient(uri, ctx) as client:
        await client.auth()
        resp = await client.management_creation(action=action, **body)
        print(json.dumps(resp, indent=2))


async def _run_inference_http(
    uri: str,
    ctx: AuthContext,
    vm_id: str,
    vm_ip: Optional[str],
    container_id: str,
    model_name: str,
    payload_path: str,
) -> None:
    """
    Run a single HTTP inference using a JSON payload describing inputs.

    The payload file may contain:
    - a JSON list: treated as the `inputs` list, or
    - a JSON object with `inputs` (legacy), or
    - a JSON object with `request.inputs` (canonical).
    """

    with open(payload_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        raw_inputs = data
    elif isinstance(data, dict):
        request = data.get("request")
        if isinstance(request, dict) and isinstance(request.get("inputs"), list):
            raw_inputs = request.get("inputs")
        else:
            raw_inputs = data.get("inputs")
    else:
        raw_inputs = None
    if not isinstance(raw_inputs, list):
        raise SystemExit(
            "inference-http payload must be either a JSON list of inputs, "
            "or a JSON object with `inputs`, or a JSON object with `request.inputs`."
        )

    try:
        inputs = [InferenceInput(**item) for item in raw_inputs]
    except Exception as exc:
        raise SystemExit(
            f"Invalid `inputs` payload for Triton inference: {exc}"
        ) from exc

    async with TcmWebSocketClient(uri, ctx) as client:
        await client.auth()
        resp = await client.inference_http(
            vm_id=vm_id,
            vm_ip=vm_ip,
            container_id=container_id,
            model_name=model_name,
            inputs=inputs,
        )
        print(json.dumps(resp, indent=2))


def _run_model_analyze(path: str, name: str) -> None:
    AnalyzeModelAction(model_path=path, name=name).run(print_json=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="tcm-client-cli",
        description=(
            "Minimal CLI on top of tcm-client.\n\n"
            "Typical uses:\n"
            "  - quick smoke check: auth + info.queue_stats\n"
            "  - small load test against info.queue_stats to feed /metrics\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--uri",
        default=os.getenv("TCM_WS_URI", "ws://127.0.0.1:8000/ws"),
        help="WebSocket URI of Triton Client Manager (/ws). "
        "Default: %(default)s or $TCM_WS_URI if set.",
    )
    parser.add_argument(
        "--uuid",
        default=os.getenv("TCM_CLIENT_UUID", "tcm-client-cli"),
        help="Client UUID for the WebSocket session. "
        "Default: %(default)s or $TCM_CLIENT_UUID if set.",
    )
    parser.add_argument(
        "--token",
        default=os.getenv("TCM_CLIENT_TOKEN"),
        help="Auth token (JWT / opaque) to send in the auth payload. "
        "Default: $TCM_CLIENT_TOKEN.",
    )
    parser.add_argument(
        "--sub",
        default=os.getenv("TCM_CLIENT_SUB"),
        help="Client subject (sub). Default: $TCM_CLIENT_SUB or falls back to uuid.",
    )
    parser.add_argument(
        "--tenant-id",
        default=os.getenv("TCM_CLIENT_TENANT_ID"),
        help=(
            "Tenant / project identifier. Default: $TCM_CLIENT_TENANT_ID. "
            "If omitted, the SDK will fall back to 'dev-tenant' when building the auth client block."
        ),
    )
    parser.add_argument(
        "--roles",
        default=os.getenv("TCM_CLIENT_ROLES", "inference,management"),
        help="Comma-separated roles (e.g. 'inference,management'). "
        "Default: %(default)s or $TCM_CLIENT_ROLES.",
    )

    subparsers = parser.add_subparsers(dest="command", required=False)

    # queue-stats: default command
    qs = subparsers.add_parser(
        "queue-stats",
        help="Run auth + info.queue_stats once or as a small load test.",
    )
    qs.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="Number of requests to send. Default: 1.",
    )
    qs.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Number of concurrent tasks when repeat > 1. Default: 1.",
    )

    # management: generic management action with JSON payload
    mgmt = subparsers.add_parser(
        "management",
        help="Run a generic management action using a JSON payload body.",
    )
    mgmt.add_argument(
        "--action",
        default="creation",
        help='Management action name (default: "creation").',
    )
    mgmt.add_argument(
        "--payload",
        required=True,
        help=(
            "Path to a JSON file containing the management payload body "
            "(fields such as openstack/docker/minio/vm_id/container_id, "
            "without the top-level uuid/type/payload envelope)."
        ),
    )

    # inference-http: single HTTP inference with JSON inputs
    inf = subparsers.add_parser(
        "inference-http",
        help="Run a single HTTP inference using a JSON file with `inputs`.",
    )
    inf.add_argument("--vm-id", required=True, help="OpenStack VM identifier.")
    inf.add_argument(
        "--vm-ip",
        required=False,
        default=os.getenv("TCM_VM_IP"),
        help=(
            "Optional VM IP used for routing. Default: $TCM_VM_IP. "
            "If omitted, the manager may try to derive it from its Docker cache."
        ),
    )
    inf.add_argument(
        "--container-id",
        required=True,
        help="Docker container identifier where Triton is running.",
    )
    inf.add_argument(
        "--model-name",
        required=True,
        help="Name of the Triton model to invoke.",
    )
    inf.add_argument(
        "--payload",
        required=True,
        help=(
            "Path to a JSON file containing an `inputs` list compatible with "
            "Triton HTTP inference."
        ),
    )

    # model-analyze: inspect ONNX file and print typed report
    analyze = subparsers.add_parser(
        "model-analyze",
        help="Inspect an ONNX model file and print a typed inputs/outputs report.",
    )
    analyze.add_argument(
        "--path",
        required=True,
        help="Path to an ONNX model file.",
    )
    analyze.add_argument(
        "--name",
        required=True,
        help="Logical model name to include in the report.",
    )

    args = parser.parse_args()
    if not args.command:
        args.command = "queue-stats"

    roles = _parse_roles(args.roles)
    ctx = AuthContext(
        uuid=args.uuid,
        token=args.token,
        sub=args.sub,
        tenant_id=args.tenant_id,
        roles=roles,
    )

    if args.command == "queue-stats":
        asyncio.run(
            _run_queue_stats(
                uri=args.uri,
                ctx=ctx,
                repeat=max(1, int(args.repeat)),
                concurrency=max(1, int(args.concurrency)),
            )
        )
    elif args.command == "management":
        asyncio.run(
            _run_management_creation(
                uri=args.uri,
                ctx=ctx,
                action=args.action,
                payload_path=args.payload,
            )
        )
    elif args.command == "inference-http":
        asyncio.run(
            _run_inference_http(
                uri=args.uri,
                ctx=ctx,
                vm_id=args.vm_id,
                vm_ip=args.vm_ip,
                container_id=args.container_id,
                model_name=args.model_name,
                payload_path=args.payload,
            )
        )
    elif args.command == "model-analyze":
        _run_model_analyze(path=args.path, name=args.name)
    else:
        raise SystemExit(f"Unknown command: {args.command!r}")


if __name__ == "__main__":
    main()
