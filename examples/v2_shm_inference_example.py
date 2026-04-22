"""
v2.0.0-GOLDEN example: POSIX SHM → Triton Client Manager (metadata only).

This example demonstrates the *client-side* workflow:
  1) Create a POSIX shared memory segment (posix_ipc)
  2) Write a NumPy array into it (mmap)
  3) Send an inference message containing SHMReference metadata to the Manager over WebSocket

Notes:
- The manager must be started on a host where /dev/shm is available.
- The SHM path currently targets HTTP inference in the manager; gRPC streaming SHM is not supported yet.
- You need to ensure the Triton model input matches:
    - `name`
    - `shape`
    - `dtype` (Triton datatype string, e.g. "FP32")

Dependencies (example-only):
  pip install posix_ipc numpy websockets
"""

from __future__ import annotations

import asyncio
import json
import mmap
import os
from dataclasses import dataclass
from typing import Sequence

import numpy as np
import posix_ipc
import websockets


@dataclass(frozen=True)
class SHMReference:
    name: str
    shm_key: str
    offset: int
    byte_size: int
    shape: list[int]
    dtype: str


def _triton_dtype_for_numpy(arr: np.ndarray) -> str:
    if arr.dtype == np.float32:
        return "FP32"
    if arr.dtype == np.float16:
        return "FP16"
    if arr.dtype == np.int64:
        return "INT64"
    if arr.dtype == np.int32:
        return "INT32"
    raise ValueError(f"Unsupported dtype for example: {arr.dtype}")


def create_shm_from_array(*, shm_key: str, arr: np.ndarray) -> SHMReference:
    """
    Create a POSIX shm segment and write `arr` bytes into it.

    Returns a SHMReference pointing to the segment.
    """
    if not shm_key.startswith("/"):
        raise ValueError("POSIX shm name must start with '/' (e.g. '/tcm_demo_input0')")

    data = arr.tobytes(order="C")
    byte_size = len(data)

    # Create or recreate segment
    try:
        posix_ipc.unlink_shared_memory(shm_key)
    except Exception:
        pass

    shm = posix_ipc.SharedMemory(shm_key, flags=posix_ipc.O_CREX, size=byte_size)
    try:
        mm = mmap.mmap(shm.fd, byte_size, access=mmap.ACCESS_WRITE)
        try:
            mm.seek(0)
            mm.write(data)
            mm.flush()
        finally:
            mm.close()
    finally:
        os.close(shm.fd)

    return SHMReference(
        name="INPUT__0",
        shm_key=shm_key,
        offset=0,
        byte_size=byte_size,
        shape=list(arr.shape),
        dtype=_triton_dtype_for_numpy(arr),
    )


async def main() -> None:
    uri = "ws://127.0.0.1:8000/ws"

    # Example tensor
    x = np.random.rand(1, 3, 224, 224).astype(np.float32)
    ref = create_shm_from_array(shm_key="/tcm_demo_input0", arr=x)

    async with websockets.connect(uri, max_size=10 * 1024 * 1024) as ws:
        # Negotiate capabilities (json + shm)
        await ws.send(
            json.dumps(
                {
                    "uuid": "shm-client-1",
                    "type": "auth",
                    "payload": {
                        "token": None,
                        "capability": ["json", "shm"],
                        "client": {"sub": "dev-user", "tenant_id": "dev-tenant", "roles": ["inference"]},
                    },
                }
            )
        )
        auth_ok = json.loads(await ws.recv())
        print("auth:", auth_ok)

        # Send inference with SHMReference input
        await ws.send(
            json.dumps(
                {
                    "uuid": "shm-client-1",
                    "type": "inference",
                    "payload": {
                        "vm_ip": "127.0.0.1",
                        "container_id": "container-id-here",
                        "model_name": "my_model",
                        "request": {
                            "protocol": "http",
                            "inputs": [
                                {
                                    "name": ref.name,
                                    "shm_key": ref.shm_key,
                                    "offset": ref.offset,
                                    "byte_size": ref.byte_size,
                                    "shape": ref.shape,
                                    "dtype": ref.dtype,
                                }
                            ],
                        },
                    },
                }
            )
        )
        resp = json.loads(await ws.recv())
        print("response:", resp)


if __name__ == "__main__":
    asyncio.run(main())

