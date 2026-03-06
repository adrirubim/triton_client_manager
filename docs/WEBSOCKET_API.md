# WebSocket API – Triton Client Manager

Contract of the WebSocket API exposed at `/ws`.

This file acts as an **alias and entry point** to the official WebSocket API
contract for Triton Client Manager. The **canonical source of truth** for the
contract (message formats, examples, and errors) lives in:

- `docs/API_CONTRACTS.md`

There you will find:

- Standard message format:
  - Required fields: `uuid`, `type`, `payload`.
  - Supported types: `auth`, `info`, `management`, `inference`.
- Detailed sections for:
  - `Auth` (including payload with `token` and `client` block).
  - `Info` (for example `info.queue_stats`).
  - `Management` (creation and deletion with flat and nested payloads).
  - `Inference` (required fields and example payload).
- Error contract:
  - Structure `{"type": "error", "payload": {"message": "..."}}`.
  - WebSocket close codes (for example `1008`, `1009`) and typical causes.

When you see references to `docs/WEBSOCKET_API.md` in this repository (for example in):

- `docs/internal/PROJECT_STATES.md`
- `MANAGER/_______WEBSOCKET/README.md`
- Comments in `MANAGER/tests/test_client_sdk_contract.py`

you should treat them as a direct alias to `docs/API_CONTRACTS.md`.

When in doubt, **always consider `API_CONTRACTS.md` as the most up‑to‑date
contract** and keep your integrations and contract tests in sync with that
file.

---

## 1. Base message

All messages (requests and responses) use the same envelope:

- `uuid` (string, **required**): WebSocket client identifier. It must be the same for all requests in a given session.
- `type` (string, **required**): message type.
- `payload` (object, **required**): message-specific contents.

Generic request example:

```json
{
  "uuid": "frontend-123",
  "type": "info",
  "payload": {
    "action": "queue_stats"
  }
}
```

If any required field is missing, the server responds with:

```json
{
  "type": "error",
  "payload": {
    "message": "Missing required field: 'uuid'"
  }
}
```

---

## 2. Supported message types

### 2.1 `auth` – Authentication

The **first** request on each connection must be of type `auth`. It establishes the
identity and authorization model for the WebSocket session.

#### Auth payload

The recommended payload shape is:

```json
{
  "uuid": "frontend-123",
  "type": "auth",
  "payload": {
    "token": "opaque-or-jwt-token",
    "client": {
      "sub": "user-123",
      "tenant_id": "tenant-abc",
      "roles": ["inference", "management"]
    }
  }
}
```

**SDK equivalent (Python):**

```python
from tcm_client import AuthContext, TcmWebSocketClient

ctx = AuthContext(
    uuid="frontend-123",
    token="opaque-or-jwt-token",
    sub="user-123",
    tenant_id="tenant-abc",
    roles=["inference", "management"],
)

async with TcmWebSocketClient(uri, ctx) as client:
    await client.auth()
```

- `uuid` (string): stable identifier for the client within this connection.
- `payload.token` (string): authentication token (for example, JWT or API key) issued
  by your identity provider.
- `payload.client.sub` (string): subject / user id.
- `payload.client.tenant_id` (string): tenant / project identifier.
- `payload.client.roles` (array of strings): roles granted to the client. Typical
  roles:
  - `"inference"` – can send `inference` messages.
  - `"management"` – can send `management` messages.
  - `"admin"` – full access.

The server validates that:

- `payload` is an object.
- If `client` is present, it contains `sub`, `tenant_id`, and `roles` (list of
  strings).
- Depending on configuration (`MANAGER/config/websocket.yaml` → `auth`), it may
  also enforce that `payload.token` is present and that it includes certain
  claims (`exp`, `aud`, `iss`).

If the structure is invalid, or the token does not meet the configured policy,
the server responds with an error and closes the connection (close code `1008`).

> Backwards compatibility: for local tests and smoke flows, an empty payload
> (`"payload": {}`) is still accepted and treated as an unauthenticated client
> with no special roles. In that mode, only basic `info` calls are expected.
> This corresponds to `auth.mode: "simple"` in `websocket.yaml`.

##### Token validation modes

The WebSocket server supports two high-level modes:

- **Simple mode** (`auth.mode: "simple"`, default):
  - `payload.token` is treated as opaque.
  - No local claim validation is performed; it is assumed that an upstream
    IdP/gateway already validated the token.
  - `payload.client` is still validated structurally and used for authorization
    (`roles`).

- **Strict mode** (`auth.mode: "strict"`):
  - `payload.token` is required (unless `auth.require_token` is explicitly set
    to `false`).
  - The server parses the JWT payload and enforces:
    - Presence of all claims listed in `auth.required_claims`.
    - `exp` (if present) is not expired (with `auth.leeway_seconds` seconds of
      allowed clock skew).
    - `iss` and `aud` (if configured) match `auth.issuer` and
      `auth.audience`.
  - Signature validation depends on configuration:
    - If neither `jwks_url` nor `public_key_pem` is configured, strict mode
      validates **claim semantics only** (presence of required claims, `exp`,
      `iss`, `aud` when configured).
    - If `jwks_url` (JWKS) or `public_key_pem` (public key / shared secret for
      HS* in dev) is configured, the server verifies the JWT signature
      cryptographically (via PyJWT) and restricts algorithms to
      `auth.algorithms`.
  - In production, it is still recommended to validate tokens upstream (API
    gateway / IdP) and treat strict mode as defence-in-depth.

#### Successful response

```json
{
  "type": "auth.ok"
}
```

#### Typical errors

- First message is not `auth`:

  ```json
  {
    "type": "error",
    "payload": {
      "message": "First message must be type 'auth'"
    }
  }
  ```

- UUID already connected:

  ```json
  {
    "type": "error",
    "payload": {
      "message": "UUID 'frontend-123' is already connected"
    }
  }
  ```

- Invalid auth payload (missing required fields in `client`):

  ```json
  {
    "type": "error",
    "payload": {
      "message": "Invalid auth payload: expected 'client.sub', 'client.tenant_id', and 'client.roles'"
    }
  }
  ```

- Invalid or expired token (in strict mode, exact message depends on the root cause):

  ```json
  {
    "type": "error",
    "payload": {
      "message": "Invalid token: Token has expired"
    }
  }
  ```

On an error in the first message, the server may close the connection with
WebSocket close code `1008`.

---

### 2.2 `info` – Information and `queue_stats`

Allows querying system information, starting with queue statistics.

**Request – `queue_stats`:**

```json
{
  "uuid": "frontend-123",
  "type": "info",
  "payload": {
    "action": "queue_stats"
  }
}
```

**SDK equivalent (Python):**

```python
info = await client.info_queue_stats()
print(info)
```

**Successful response (`info_response`):**

```json
{
  "type": "info_response",
  "payload": {
    "job_id": null,
    "request_type": "queue_stats",
    "status": "success",
    "data": {
      "info_users": 1,
      "management_users": 0,
      "inference_users": 0,
      "total_users": 1,
      "total_queued": 0,
      "info_total_queued": 0,
      "management_total_queued": 0,
      "inference_total_queued": 0,
      "executor_info_pending": 0,
      "executor_management_pending": 0,
      "executor_inference_pending": 0,
      "executor_info_available": 2,
      "executor_management_available": 1,
      "executor_inference_available": 5
    }
  }
}
```

Other values of `payload.action` are reserved for future extensions and will return a success response with an informational text in `data.message`.

---

### 2.3 `management` – Resource creation and deletion

Messages of type `management` create and delete resources (VMs, containers, Triton servers, etc.) using the actions defined in `management_actions_available` in `config/jobs.yaml`.

**Typical actions** (depending on configuration):

- `creation`
- `deletion`
- `create_vm`, `create_container`, `create_server`
- `delete_vm`, `delete_container`, `delete_server`

**Generic request:**

```json
{
  "uuid": "frontend-123",
  "type": "management",
  "payload": {
    "action": "creation",
    "openstack": { /* VM parameters */ },
    "docker": { /* container parameters */ },
    "minio": { /* storage parameters */ }
  }
}
```

**SDK equivalent (Python):**

```python
resp = await client.management_creation(
    action="creation",
    openstack={...},
    docker={...},
    minio={...},
)
print(resp)
```

**Standard response:**

The server reuses the original `type` and `uuid`, but normalizes `payload`:

```json
{
  "uuid": "frontend-123",
  "type": "management",
  "payload": {
    "status": true,
    "data": {
      "...": "..."
    }
  }
}
```

On error (for example, unknown action, OpenStack/Docker/Triton failure) the response keeps the same shape but with `status: false` and `data` containing the error message:

```json
{
  "uuid": "frontend-123",
  "type": "management",
  "payload": {
    "status": false,
    "data": "JobActionNotFound: unknown_action"
  }
}
```

> Note: current integration tests focus on `auth` + `info` and on validating the error contract. `management` flows require real external services and are mainly covered by unit and regression tests.

---

### 2.4 `inference` – Inference requests

Inference requests use messages of type `inference`. The server orchestrates the call to Triton and sends one or more responses using the same `uuid`.

**Generic request (HTTP):**

```json
{
  "uuid": "frontend-123",
  "type": "inference",
  "payload": {
    "vm_id": "openstack-vm-uuid",
    "container_id": "docker-container-id",
    "model_name": "example-model",
    "inputs": [
      {"name": "input_0", "type": "TYPE_FP32", "dims": 4, "value": [1.0, 2.0, 3.0, 4.0]}
    ],
    "request": {"protocol": "http"}
  }
}
```

**SDK equivalent (Python):**

```python
inputs = [
    {"name": "input_0", "type": "TYPE_FP32", "dims": 4, "value": [1.0, 2.0, 3.0, 4.0]},
]
resp = await client.inference_http(
    vm_id="openstack-vm-uuid",
    container_id="docker-container-id",
    model_name="example-model",
    inputs=inputs,
)
```

**Typical responses:**

Inference responses always have `type: "inference"` and reuse the client `uuid`. The `payload` field follows this schema:

```json
{
  "type": "inference",
  "uuid": "frontend-123",
  "payload": {
    "data": { /* returned data or error */ },
    "status": "COMPLETED",
    "model_name": "example-model"
  }
}
```

The `status` field can take values such as:

- `"COMPLETED"`: request finished successfully (HTTP mode) or gRPC flow completed.
- `"FAILED"`: validation error, Triton failure, or other unexpected error.

Example of an error due to uninitialized Triton configuration (typical in test environments without a real Triton instance):

```json
{
  "type": "inference",
  "uuid": "frontend-123",
  "payload": {
    "data": "Unexpected error: TritonThread.triton_infer is not initialized",
    "status": "FAILED",
    "model_name": null
  }
}
```

> Note: in gRPC mode, the server may send several `inference` messages with different `status` values (for example, start/ongoing/completed); the high-level contract (`type`, `uuid`, `payload` shape) remains stable.

---

## 3. Protocol errors

Regardless of the message type, the server may respond with protocol error messages when:

- The input JSON is invalid.
- Required fields are missing (`uuid`, `type`, `payload`).
- `type` is not in the configured list of valid types.
- The `uuid` of a message after `auth` does not match the authenticated `uuid`.
- The message size exceeds the configured limit.

In all these cases, the error message has the form:

```json
{
  "type": "error",
  "payload": {
    "message": "<human‑readable error description>"
  }
}
```

Examples observed in the server:

- Invalid JSON:

  ```json
  {
    "type": "error",
    "payload": {
      "message": "Invalid JSON format"
    }
  }
  ```

- Invalid type:

  ```json
  {
    "type": "error",
    "payload": {
      "message": "Invalid type 'unknown'. Must be one of: [\"auth\", \"info\", \"management\", \"inference\"]"
    }
  }
  ```

- UUID different from the authenticated one:

  ```json
  {
    "type": "error",
    "payload": {
      "message": "UUID mismatch. Expected 'frontend-123', got 'other'"
    }
  }
  ```

---

## 4. Minimal recommended flow for integrators

An external integrator (frontend, other service) should, at minimum, follow this flow:

1. **Open a WebSocket connection** to `ws://<host>:<port>/ws`.
2. **Send an `auth` message** with a stable `uuid` for the client.
3. Wait for an `auth.ok` response and, if a `type: "error"` arrives, log the reason and either retry or surface an error to the user.
4. **Send an `info` message with `action: "queue_stats"`** to verify that the system is accepting requests.
5. Optionally, send `management` or `inference` messages, depending on the capabilities and constraints of your deployment.
6. Close the WebSocket connection when it is no longer needed.

For functional client examples, see:

- `MANAGER/_______WEBSOCKET/client.py` — minimal interactive client.
- `MANAGER/_______WEBSOCKET/sdk.py` — lightweight SDK (`TcmWebSocketClient`) and quickstart helpers.
- `MANAGER/_______WEBSOCKET/README.md` — “copy/paste and run” quickstart using the SDK.

---

## 5. SDK (Python) quick reference

When using the official Python SDK (`tcm-client`), the minimal flow described
above can be expressed as:

```python
import asyncio

from tcm_client import AuthContext, TcmWebSocketClient


async def main() -> None:
    uri = "ws://127.0.0.1:8000/ws"

    ctx = AuthContext(
        uuid="frontend-123",
        token="opaque-or-jwt-token",
        sub="user-123",
        tenant_id="tenant-abc",
        roles=["inference", "management"],
    )

    async with TcmWebSocketClient(uri, ctx) as client:
        # 1) Auth
        await client.auth()

        # 2) info.queue_stats
        info = await client.info_queue_stats()
        print(info)
```

For management and inference flows, refer to the examples in `sdk/README.md`,
which build directly on the JSON contracts described in this file.

