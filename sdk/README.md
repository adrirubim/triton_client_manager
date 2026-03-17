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

## Command-line interface (`tcm-client-cli`)

For quick checks and lightweight load tests, the SDK exposes a small CLI entrypoint:

```bash
python -m pip install tcm-client

# Basic smoke: auth + info.queue_stats once
tcm-client-cli --uri ws://127.0.0.1:8000/ws queue-stats

# Or with environment variables (recommended in CI / shared envs):
export TCM_WS_URI=ws://manager.example.com/ws
export TCM_CLIENT_UUID=ci-smoke-client
export TCM_CLIENT_TOKEN="opaque-or-jwt-token"
export TCM_CLIENT_TENANT_ID="tenant-ci"
export TCM_CLIENT_ROLES="inference,management"

tcm-client-cli queue-stats

# Small load test feeding /metrics (N requests, M concurrent tasks)
tcm-client-cli queue-stats --repeat 50 --concurrency 5

# Management flows (creation/deletion) from JSON payloads
tcm-client-cli management --action creation --payload examples/management_creation.json
tcm-client-cli management --action deletion --payload examples/management_deletion.json

# Single HTTP inference using a JSON file with `inputs`
tcm-client-cli inference-http \
  --vm-id openstack-vm-uuid \
  --container-id docker-container-id \
  --model-name example-model \
  --payload examples/inference_inputs.json
```

Environment variables understood by the CLI:

- `TCM_WS_URI` – WebSocket URI (defaults to `ws://127.0.0.1:8000/ws`).
- `TCM_CLIENT_UUID` – client UUID for the session.
- `TCM_CLIENT_TOKEN` – auth token sent in the `auth` payload.
- `TCM_CLIENT_SUB` – subject (`sub`) claim; falls back to UUID when not set.
- `TCM_CLIENT_TENANT_ID` – tenant/project identifier; defaults to `dev-tenant`.
- `TCM_CLIENT_ROLES` – comma-separated roles, e.g. `inference,management`.

## Versioning and compatibility policy

The `tcm-client` SDK follows a **semantic versioning** model aligned with the
WebSocket contracts documented in `docs/WEBSOCKET_API.md` and
`docs/API_CONTRACTS.md` in the main repository:

- **MAJOR (`X.0.0`)**:
  - May introduce **backwards-incompatible** changes in the wire protocol or
    in the public Python API exposed by `tcm_client`.
  - Used when contracts in `docs/WEBSOCKET_API.md` / `docs/API_CONTRACTS.md`
    change in a way that breaks existing clients (for example, removing or
    renaming fields without a transition path).
- **MINOR (`0.Y.0` / `X.Y.0`)**:
  - Adds new capabilities in a **backwards-compatible** way (new optional
    fields, new helper methods, additional CLI commands) while keeping existing
    flows working unchanged.
- **PATCH (`X.Y.Z`)**:
  - Contains bug fixes, performance improvements, or documentation-only updates
    that do not modify the public API or the expected behaviour of existing
    methods.

Each release documents:

- the **minimum and maximum supported server versions** (or commit ranges) in
  `CHANGELOG.md`; and
- any **contract-changing server-side updates** that require a new MAJOR or
  MINOR version on the SDK side.

In general:

- if you stay within the same **MAJOR** version of `tcm-client`, you can expect
  to remain compatible with any server deployment that advertises support for
  that MAJOR in its own release notes;
- if you upgrade the server in a way that changes `docs/WEBSOCKET_API.md` or
  `docs/API_CONTRACTS.md`, bump the SDK at least at the **MINOR** level and add
  a short note in `CHANGELOG.md` describing the new expectations.

## API overview

`TcmWebSocketClient` provides a small set of focused methods that mirror the
main WebSocket flows:

| Method | Description |
| ------ | ----------- |
| `auth()` | Sends the initial `auth` message (with `token` + `client` block when provided) and expects an `auth.ok` response. |
| `info_queue_stats()` | Sends an `info` message with `action: "queue_stats"` and returns the full `info_response`. |
| `management_creation(action=\"creation\", **kwargs)` | Sends a `management` message; you pass the `action` and any OpenStack/Docker/MinIO fields via `kwargs`. |
| `inference_http(vm_id, container_id, model_name, inputs)` | Sends an HTTP inference request routed to a specific Triton server (`vm_id` + `container_id`) with typed `inputs` entries. |
| `inference_pipeline(vm_id, container_id, pipeline)` | Sends a simple HTTP pipeline (multi‑model, sequential) over the same Triton server. |

The low-level JSON contracts for these flows are documented in
`docs/WEBSOCKET_API.md` / `docs/API_CONTRACTS.md`.

## AuthContext – best practices

`AuthContext` encapsulates the identity of your integration:

- In `staging`/`prod` environments, whenever possible:
  - Set `sub` to the real user or service identifier.
  - Set `tenant_id` when you have multi‑tenant scenarios.
  - Use `roles` to reflect permissions (`["inference"]`, `["management"]`, etc.).
- The `token` should be the same token issued by your IdP/API gateway:
  - Either an opaque token validated upstream (with `auth.mode: "simple"` in the manager).
  - Or a JWT whose signature is verified by the manager (`auth.mode: "strict"` + JWKS/PEM).
- In development environments a synthetic or even empty `token` may be acceptable, but for
  production you should:
  - Integrate with your corporate IdP.
  - Align `websocket.yaml` configuration with your token model (see `SECURITY.md`).

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

### Inference – HTTP pipeline (multi‑modelo secuencial)

```python
import asyncio

from tcm_client import AuthContext, TcmWebSocketClient


async def main() -> None:
    uri = "ws://127.0.0.1:8000/ws"
    ctx = AuthContext(
        uuid="sdk-pipeline-client",
        token="opaque-or-jwt-token",
        sub="user-pipeline",
        tenant_id="tenant-inf",
        roles=["inference"],
    )

    async with TcmWebSocketClient(uri, ctx) as client:
        await client.auth()

        pipeline = [
            {
                "name": "encode",
                "model_name": "encoder",
                "protocol": "http",
                "inputs": [
                    {
                        "name": "input_0",
                        "type": "TYPE_FP32",
                        "dims": 4,
                        "value": [1.0, 2.0, 3.0, 4.0],
                    }
                ],
            },
            {
                "name": "rerank",
                "model_name": "reranker",
                "protocol": "http",
                "inputs": [
                    {
                        "name": "input_0",
                        "type": "TYPE_FP32",
                        "dims": 4,
                        "value": [0.1, 0.9, 0.2, 0.8],
                    }
                ],
            },
        ]

        resp = await client.inference_pipeline(
            vm_id="openstack-vm-uuid",
            container_id="docker-container-id",
            pipeline=pipeline,
        )
        payload = resp.get("payload", {})
        if payload.get("status") == "COMPLETED":
            data = payload.get("data", {})
            print("Encode result:", data.get("encode"))
            print("Rerank result:", data.get("rerank"))
        else:
            print("Pipeline FAILED:", payload.get("data"))


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

