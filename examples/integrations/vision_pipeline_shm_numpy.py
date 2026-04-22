from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from dataclasses import dataclass
from multiprocessing import shared_memory
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from tcm_client import AuthContext, TcmWebSocketClient

JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class ShmTensor:
    shm_key: str
    byte_size: int
    shape: List[int]
    dtype: str
    _shm: shared_memory.SharedMemory

    def close(self) -> None:
        self._shm.close()

    def unlink(self) -> None:
        # WARNING: unlink() removes the SHM name from the system namespace.
        # Only call this when you know Triton/Manager will not need it anymore.
        self._shm.unlink()


def _dtype_to_triton(dtype: np.dtype) -> str:
    if dtype == np.float32:
        return "FP32"
    if dtype == np.float16:
        return "FP16"
    if dtype == np.uint8:
        return "UINT8"
    raise ValueError(f"Unsupported dtype for demo: {dtype}")


def _allocate_shm_for_array(*, shm_name: str, array: np.ndarray) -> ShmTensor:
    shm = shared_memory.SharedMemory(name=shm_name, create=True, size=array.nbytes)
    try:
        shm_view = np.ndarray(array.shape, dtype=array.dtype, buffer=shm.buf)
        shm_view[...] = array  # one-time copy into /dev/shm (data plane stays zero-copy after this)
        triton_dtype = _dtype_to_triton(array.dtype)
        return ShmTensor(
            shm_key=f"/{shm_name}",
            byte_size=int(array.nbytes),
            shape=[int(x) for x in array.shape],
            dtype=triton_dtype,
            _shm=shm,
        )
    except Exception:
        shm.close()
        shm.unlink()
        raise


def _build_auth_message(ctx: AuthContext) -> JsonDict:
    payload: JsonDict = {}
    if any([ctx.token, ctx.sub, ctx.tenant_id, ctx.roles]):
        payload = {
            "token": ctx.token,
            "client": {
                "sub": ctx.sub or ctx.uuid,
                "tenant_id": ctx.tenant_id or "dev-tenant",
                "roles": ctx.roles or [],
            },
        }
    # v2.0.0-GOLDEN capability negotiation (Zero-Copy Era)
    payload["capability"] = ["json", "shm"]
    return {"uuid": ctx.uuid, "type": "auth", "payload": payload}


def _build_inference_message(
    *,
    ctx: AuthContext,
    vm_id: str,
    vm_ip: Optional[str],
    container_id: str,
    model_name: str,
    input_name: str,
    tensor: ShmTensor,
) -> JsonDict:
    shm_ref: JsonDict = {
        "name": input_name,
        "shm_key": tensor.shm_key,
        "offset": 0,
        "byte_size": tensor.byte_size,
        "shape": tensor.shape,
        "dtype": tensor.dtype,
    }

    payload: JsonDict = {
        "vm_id": vm_id,
        "container_id": container_id,
        "model_name": model_name,
        "request": {
            "protocol": "http",
            # SHMReference goes in request.inputs (metadata only).
            "inputs": [shm_ref],
            "allow_transient": False,
        },
    }
    if vm_ip:
        payload["vm_ip"] = vm_ip

    return {"uuid": ctx.uuid, "type": "inference", "payload": payload}


def _synthetic_vision_batch(*, batch: int, height: int, width: int, dtype: np.dtype) -> np.ndarray:
    """
    Produce a high-resolution NCHW batch without external image deps.

    Shape: [B, 3, H, W]
    """
    rng = np.random.default_rng(7)
    if dtype == np.uint8:
        return rng.integers(0, 256, size=(batch, 3, height, width), dtype=np.uint8)
    if dtype == np.float32:
        return rng.random(size=(batch, 3, height, width), dtype=np.float32)
    if dtype == np.float16:
        return rng.random(size=(batch, 3, height, width)).astype(np.float16)
    raise ValueError(f"Unsupported dtype: {dtype}")


async def main_async() -> None:
    parser = argparse.ArgumentParser(
        description="High-Performance Vision Pipeline (Zero-Copy SHM + NumPy) — v2.0.0-GOLDEN"
    )
    parser.add_argument("--ws-uri", default=os.getenv("TCM_WS_URI", "ws://127.0.0.1:8000/ws"))
    parser.add_argument("--vm-id", required=True)
    parser.add_argument("--vm-ip", default=os.getenv("TCM_VM_IP"))
    parser.add_argument("--container-id", required=True)
    parser.add_argument("--model-name", required=True)
    parser.add_argument("--input-name", default="INPUT__0")
    parser.add_argument("--batch", type=int, default=2)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--dtype", choices=["uint8", "fp16", "fp32"], default="fp32")
    parser.add_argument("--shm-name", default="tcm_vision_batch0")
    parser.add_argument("--keep-shm", action="store_true", help="Do not unlink SHM segment (debug)")
    args = parser.parse_args()

    dtype: np.dtype
    if args.dtype == "uint8":
        dtype = np.uint8
    elif args.dtype == "fp16":
        dtype = np.float16
    else:
        dtype = np.float32

    batch = _synthetic_vision_batch(
        batch=args.batch,
        height=args.height,
        width=args.width,
        dtype=dtype,
    )

    tensor = _allocate_shm_for_array(shm_name=args.shm_name, array=batch)
    ctx = AuthContext(
        uuid=os.getenv("TCM_CLIENT_UUID", "vision-shm-client"),
        token=os.getenv("TCM_CLIENT_TOKEN", "dummy-token"),
        sub=os.getenv("TCM_CLIENT_SUB", "vision-user"),
        tenant_id=os.getenv("TCM_CLIENT_TENANT_ID", "tenant-sdk"),
        roles=[r.strip() for r in os.getenv("TCM_CLIENT_ROLES", "inference").split(",") if r.strip()],
    )

    try:
        async with TcmWebSocketClient(args.ws_uri, ctx) as client:
            # Battle-tested pattern: we use the SDK transport, but send the exact v2.0.0-GOLDEN
            # wire contract (capability negotiation + SHMReference) directly.
            auth_msg = _build_auth_message(ctx)
            auth_resp = await client._send(auth_msg)  # type: ignore[attr-defined]
            if auth_resp.get("type") != "auth.ok":
                raise RuntimeError(f"Auth failed: {auth_resp}")

            infer_msg = _build_inference_message(
                ctx=ctx,
                vm_id=args.vm_id,
                vm_ip=args.vm_ip,
                container_id=args.container_id,
                model_name=args.model_name,
                input_name=args.input_name,
                tensor=tensor,
            )

            t0 = time.perf_counter()
            resp = await client._send(infer_msg)  # type: ignore[attr-defined]
            t1 = time.perf_counter()

            print(json.dumps({"round_trip_ms": (t1 - t0) * 1000.0, "response": resp}, indent=2))
    finally:
        tensor.close()
        if not args.keep_shm:
            tensor.unlink()


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
