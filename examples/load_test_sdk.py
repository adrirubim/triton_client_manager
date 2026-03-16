from __future__ import annotations

import argparse
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List

from tcm_client.sdk import AuthContext, InferenceInput, TcmClient

JsonDict = Dict[str, Any]


def build_auth_context() -> AuthContext:
    uuid = os.getenv("TCM_CLIENT_UUID", "load-tester")
    token = os.getenv("TCM_CLIENT_TOKEN", "dummy-token")
    sub = os.getenv("TCM_CLIENT_SUB", uuid)
    tenant_id = os.getenv("TCM_CLIENT_TENANT_ID", "tenant-sdk")
    roles = os.getenv("TCM_CLIENT_ROLES", "inference,management").split(",")

    return AuthContext(
        uuid=uuid,
        token=token,
        sub=sub,
        tenant_id=tenant_id,
        roles=[role.strip() for role in roles if role.strip()],
    )


def build_client() -> TcmClient:
    uri = os.getenv("TCM_WS_URI", "ws://127.0.0.1:8000/ws")
    return TcmClient(uri=uri, auth_ctx=build_auth_context())


def example_inputs(model_name: str) -> List[JsonDict]:
    # Este payload debe adaptarse al modelo real.
    return [
        {
            "name": "INPUT__0",
            "shape": [1, 3, 224, 224],
            "datatype": "FP32",
            "data": [0.0] * (1 * 3 * 224 * 224),
        }
    ]


def run_single_inference(vm_id: str, container_id: str, model_name: str) -> float:
    client = build_client()
    start = time.monotonic()
    inputs = [InferenceInput(**item) for item in example_inputs(model_name)]
    client.infer(
        vm_id=vm_id,
        container_id=container_id,
        model_name=model_name,
        inputs=inputs,
    )
    end = time.monotonic()
    return end - start


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple SDK load tester for TCM.")
    parser.add_argument("--vm-id", required=True)
    parser.add_argument("--container-id", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--requests", type=int, default=20)
    args = parser.parse_args()

    latencies: List[float] = []
    latencies_lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(
                run_single_inference,
                args.vm_id,
                args.container_id,
                args.model_name,
            )
            for _ in range(args.requests)
        ]

        for future in as_completed(futures):
            try:
                latency = future.get_timeout(0) if hasattr(future, "get_timeout") else future.result()
            except Exception:
                continue
            else:
                with latencies_lock:
                    latencies.append(latency)

    if not latencies:
        print("No se han registrado latencias (todas las peticiones han fallado).")
        return

    total = sum(latencies)
    print(f"Total requests: {len(latencies)}")
    print(f"Avg latency: {total / len(latencies):.3f}s")
    print(f"Min latency: {min(latencies):.3f}s")
    print(f"Max latency: {max(latencies):.3f}s")


if __name__ == "__main__":
    main()

