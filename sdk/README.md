# tcm-client (Python SDK for Triton Client Manager)

This package provides a small, official Python SDK for talking to the
**Triton Client Manager** WebSocket API.

It wraps the `/ws` endpoint with a high-level client (`TcmWebSocketClient`)
and helpers like `quickstart_queue_stats` so you can integrate without
vendoring code from the server repository.

## Installation

PyPI: https://pypi.org/project/tcm-client/

Supported Python versions: **3.10 – 3.12**.

Install from PyPI:

```bash
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install tcm-client
```

For testing against TestPyPI (for example, when validating pre-releases), you can still use:

```bash
python -m pip install --upgrade pip
python -m pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple \
  tcm-client
```

## Quickstart

```python
import asyncio

from tcm_client import AuthContext, TcmWebSocketClient


async def main() -> None:
    uri = "ws://127.0.0.1:8000/ws"

    ctx = AuthContext(
        uuid="sdk-quickstart-client",
        token="opaque-or-jwt-token",
        sub="user-sdk",
        tenant_id="tenant-sdk",
        roles=["inference", "management"],
    )

    async with TcmWebSocketClient(uri, ctx) as client:
        await client.auth()
        info = await client.info_queue_stats()
        print(info)


if __name__ == "__main__":
    asyncio.run(main())
```

## API overview

`TcmWebSocketClient` provides a small set of focused methods that mirror the
main WebSocket flows:

| Method | Description |
| ------ | ----------- |
| `auth()` | Sends the initial `auth` message (with `token` + `client` block when provided) and expects an `auth.ok` response. |
| `info_queue_stats()` | Sends an `info` message with `action: "queue_stats"` and returns the full `info_response`. |
| `management_creation(action=\"creation\", **kwargs)` | Sends a `management` message; you pass the `action` and any OpenStack/Docker/MinIO fields via `kwargs`. |
| `inference_http(vm_id, container_id, model_name, inputs)` | Sends an HTTP inference request routed to a specific Triton server (`vm_id` + `container_id`) with typed `inputs` entries. |

The low-level JSON contracts for these flows are documented in
`docs/WEBSOCKET_API.md` / `docs/API_CONTRACTS.md`.

## Examples

### Management – creation flow

```python
import asyncio

from tcm_client import AuthContext, TcmWebSocketClient


async def main() -> None:
    uri = "ws://127.0.0.1:8000/ws"
    ctx = AuthContext(
        uuid="sdk-management-client",
        token="opaque-or-jwt-token",
        sub="user-management",
        tenant_id="tenant-mgmt",
        roles=["management"],
    )

    async with TcmWebSocketClient(uri, ctx) as client:
        await client.auth()

        resp = await client.management_creation(
            action="creation",
            openstack={
                "vm_name": "demo-vm",
                "image": "ubuntu-22.04",
                "flavor": "m1.medium",
            },
            docker={
                "image": "nvcr.io/nvidia/tritonserver:23.08-py3",
                "command": "tritonserver --model-repository=/models",
            },
            minio={
                "bucket": "models",
                "prefix": "example-model/",
            },
        )

        payload = resp.get("payload", {})
        if payload.get("status") is True:
            print("Management creation OK:", payload.get("data"))
        else:
            print("Management creation FAILED:", payload.get("data"))


if __name__ == "__main__":
    asyncio.run(main())
```

### Management – deletion flow (flat payload)

Deletion accepts both nested (`openstack.vm_id`, `docker.container_id`) and flat fields. This example shows the flat form:

```python
import asyncio

from tcm_client import AuthContext, TcmWebSocketClient


async def main() -> None:
    uri = "ws://127.0.0.1:8000/ws"
    ctx = AuthContext(
        uuid="sdk-deletion-client",
        token="opaque-or-jwt-token",
        sub="user-deletion",
        tenant_id="tenant-mgmt",
        roles=["management"],
    )

    async with TcmWebSocketClient(uri, ctx) as client:
        await client.auth()

        resp = await client.management_creation(
            action="deletion",
            vm_id="openstack-vm-uuid",
            container_id="docker-container-id",
            vm_ip="10.0.0.10",
        )

        payload = resp.get("payload", {})
        if payload.get("status") is True:
            print("Management deletion OK:", payload.get("data"))
        else:
            print("Management deletion FAILED:", payload.get("data"))


if __name__ == "__main__":
    asyncio.run(main())
```

### Inference – HTTP flow

```python
import asyncio

from tcm_client import AuthContext, TcmWebSocketClient


async def main() -> None:
    uri = "ws://127.0.0.1:8000/ws"
    ctx = AuthContext(
        uuid="sdk-inference-client",
        token="opaque-or-jwt-token",
        sub="user-inference",
        tenant_id="tenant-inf",
        roles=["inference"],
    )

    async with TcmWebSocketClient(uri, ctx) as client:
        await client.auth()

        inputs = [
            {"name": "input_0", "type": "TYPE_FP32", "dims": 4, "value": [1.0, 2.0, 3.0, 4.0]},
        ]
        resp = await client.inference_http(
            vm_id="openstack-vm-uuid",
            container_id="docker-container-id",
            model_name="example-model",
            inputs=inputs,
        )
        payload = resp.get("payload", {})

        status = payload.get("status")
        if status == "COMPLETED":
            print("Inference result:", payload.get("data"))
        else:
            # Typical error handling path: log message, maybe retry or reconnect.
            print("Inference FAILED:", payload.get("data"))


if __name__ == "__main__":
    asyncio.run(main())
```

## Error handling and reconnect guidance

- The server can respond with `{"type": "error", "payload": {"message": "..."}}` on protocol and policy failures.
- `TcmWebSocketClient` raises `RuntimeError` when a response doesn't match the expected flow (for example, `auth()` not returning `auth.ok`).

Recommended pattern:

```python
try:
    async with TcmWebSocketClient(uri, ctx) as client:
        await client.auth()
        info = await client.info_queue_stats()
except Exception as exc:
    # Log and reconnect with backoff in your integration.
    print("SDK call failed:", exc)
```

For full API contract details (message format, types and examples), see the
main project documentation in the main repository:

- WebSocket contract: `docs/WEBSOCKET_API.md`
- Architecture and runtime: `docs/ARCHITECTURE.md`

