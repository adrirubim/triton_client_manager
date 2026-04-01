# API Contracts

Canonical source of truth for WebSocket message formats and payloads.

---

## Table of Contents

- [Message Format](#message-format)
- [Auth](#auth)
- [Info](#info)
- [Management](#management)
- [Deletion Payload](#deletion-payload)
- [Inference](#inference)
- [Common Validation Failures](#common-validation-failures)

---

## Message Format

All messages must be JSON with:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `uuid` | string | Yes | Client identifier (top level) |
| `type` | string | Yes | `auth`, `info`, `management`, or `inference` |
| `payload` | object | Yes | Action-specific data |

### Error contract (protocol-level)

The server uses `{"type": "error", "payload": {"message": "..."}}` for **protocol-level** errors, including:

- invalid JSON (especially on the first message),
- missing required envelope fields (`uuid`, `type`, `payload`),
- invalid `type` (not in the configured `valid_types` list),
- first message is not `auth`,
- UUID mismatch after auth,
- rate limit violations.

> Note: **business / handler errors** for `info`, `management`, and `inference` do **not** use `type: "error"`.
> They use the response shapes defined in their sections below (for example `info_response.status="error"`,
> `management.payload.status=false`, or `inference.payload.status="FAILED"`).

WebSocket close codes:

- `1008` — Policy violation / protocol error (invalid JSON on first message, missing required fields, wrong first `type`, UUID mismatch on subsequent messages).
- `1009` — Message too big (payload size above `max_message_bytes`).

## Auth

The first message after connection must be `auth`.

**Request:**

```json
{"type": "auth", "uuid": "client-id", "payload": {}}
```

**Success response:**

```json
{"type": "auth.ok"}
```

**Failure:** Connection closed with code 1008.

## Info

**Request:**

```json
{"type": "info", "uuid": "client-id", "payload": {"action": "queue_stats"}}
```

Supported `action` / `request_type`: `queue`, `queue_stats`. Other types return `"not implemented"`.

**Response:**

```json
{
  "type": "info_response",
  "payload": {
    "job_id": null,
    "request_type": "queue_stats",
    "status": "success",
    "data": { ... }
  }
}
```

Notes (as implemented):

- The server accepts `payload.action` (canonical) and also `payload.request_type` (legacy/compat).
- Unknown actions do **not** fail the request; they return `status: "success"` with an informational message in `payload.data.message`.

## Management

**Request:**

```json
{
  "type": "management",
  "uuid": "client-id",
  "payload": {
    "action": "creation",
    "openstack": { ... },
    "docker": { ... },
    "minio": { ... }
  }
}
```

**Actions:** `creation`, `deletion`, `create_vm`, `create_container`, `create_server`, `delete_server`, `delete_container`, `delete_vm` (from `management_actions_available` in `config/jobs.yaml`).

**Response (as implemented):**

The server responds with:

```json
{
  "uuid": "client-id",
  "type": "management",
  "payload": {
    "status": true,
    "data": { "...": "..." }
  }
}
```

On error, the response keeps the same shape but sets `payload.status=false` and `payload.data` to an error string.

Notes (as implemented):

- Some authorization failures are returned as `type: "error"` with a message such as `Forbidden: missing 'management' role` (role checks happen before the job is queued).

### Idempotency and retries (management)

- `management.creation` is **not guaranteed to be strictly idempotent** across all external failure modes (OpenStack, Docker, Triton), but the server applies **best-effort rollback**:
  - if container creation fails, the VM is deleted;
  - if Triton server creation fails, both container and VM are deleted where possible;
  - failures in rollback are propagated as errors in the response payload.
- `management.deletion` is **idempotent at the API level**:
  - deleting an already-removed VM/container is treated as a no-op by the manager;
  - errors from individual delete steps are aggregated and returned in a single `JobDeletionFailed` message.
- Clients that need **at-least-once semantics** SHOULD:
  - treat any non-`True` `status` as a signal to reconcile state (for example, list VMs/containers and re-issue a deletion with a normalized payload);
  - log job identifiers and external resource IDs (`vm_id`, `container_id`) to avoid duplicate creates when retrying after unknown failures (network timeouts, connection drops).

## Deletion Payload

Deletion accepts **flat** or **nested** payloads. Normalization rules:

| Field | Flat source | Nested source |
|-------|-------------|---------------|
| `vm_id` | `payload.vm_id` | `payload.openstack.vm_id` |
| `container_id` | `payload.container_id` | `payload.docker.container_id` |
| `vm_ip` | `payload.vm_ip` | `payload.openstack.vm_ip` or `payload.docker.worker_ip` |

Required: `vm_id` and `container_id`. Sub-handlers receive a normalized structure with `openstack.*` and `docker.*` populated.

**Example (nested):**

```json
{
  "type": "management",
  "uuid": "user-123",
  "payload": {
    "action": "deletion",
    "openstack": {"vm_ip": "192.0.2.10", "vm_id": "openstack-vm-uuid"},
    "docker": {"container_id": "docker-container-id"}
  }
}
```

**Example (flat):**

```json
{
  "type": "management",
  "uuid": "user-123",
  "payload": {
    "action": "deletion",
    "vm_id": "openstack-vm-uuid",
    "container_id": "docker-container-id",
    "vm_ip": "192.0.2.10"
  }
}
```

## Inference

### Single-model inference

**Required fields (high-level contract):** `container_id`, `model_name`, and `inputs` (in one of the supported locations/shapes below).

Inference routes by `vm_id` and `container_id` (matches Triton server registration). Optional: `vm_ip` for handlers that use it; `request.protocol` to select HTTP/gRPC.

**Request:**

```json
{
  "type": "inference",
  "uuid": "user-123",
  "payload": {
    "vm_id": "openstack-vm-uuid",
    "vm_ip": "192.0.2.10",
    "container_id": "docker-container-id",
    "model_name": "my-model-name",
    "request": {
      "protocol": "http",
      "inputs": [
        {
          "name": "input_0",
          "type": "TYPE_FP32",
          "dims": 4,
          "value": [1.0, 2.0, 3.0, 4.0]
        }
      ]
    }
  }
}
```

**Protocol:** `payload.request.protocol` (`grpc` or `http`); default `http`.

#### Runtime validation and normalization (as implemented)

The runtime inference handler normalizes and validates the payload as follows:

- **Inputs location**
  - Canonical runtime location is `payload.request.inputs`.
  - For compatibility, if a client sends `payload.inputs`, it is mapped to `payload.request.inputs`.
- **Inputs shape**
  - Manager-internal shape: `{name, dims, type, value}`
  - SDK-friendly shape: `{name, shape, datatype, data}` (normalized to the internal shape)
- **VM addressing**
  - The runtime requires `payload.vm_ip` to contact the Triton instance.
  - If `vm_ip` is omitted, the server will attempt to derive it from the in-memory Docker cache using `container_id`.
  - If it cannot derive `vm_ip`, the request fails with an `inference` response whose `payload.status` is `"FAILED"`.

As a result:

- A request that contains `vm_id` but omits `vm_ip` may still fail if the server cannot resolve `vm_ip` from its Docker cache.

### Pipeline (multi‑model, HTTP)

For simple, sequential multi‑model pipelines (A → B → C) on the **same instance** (`vm_id` /
`container_id` and its associated `vm_ip`), the `payload` accepts a `pipeline` key:

```json
{
  "type": "inference",
  "uuid": "user-123",
  "payload": {
    "vm_id": "openstack-vm-uuid",
    "container_id": "docker-container-id",
    "vm_ip": "192.0.2.10",
    "pipeline": [
      {
        "name": "encode",
        "model_name": "encoder",
        "protocol": "http",
        "inputs": [
          {
            "name": "input_0",
            "type": "TYPE_FP32",
            "dims": 4,
            "value": [1.0, 2.0, 3.0, 4.0]
          }
        ]
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
            "value": [0.1, 0.9, 0.2, 0.8]
          }
        ]
      }
    ],
    "request": {
      "protocol": "http"
    }
  }
}
```

Notes:

- All pipeline steps share `vm_id`, `container_id` **and** `vm_ip`, which must point to the same registered Docker instance.
- Each step must provide its own `inputs`; the server does **not** automatically infer types or shapes from previous steps.
- The `name` field is used as the key in the aggregated response; if omitted, `model_name` is used instead.

**Respuesta HTTP (pipeline):**

```json
{
  "type": "inference",
  "uuid": "user-123",
  "payload": {
    "status": "COMPLETED",
    "model_name": null,
    "data": {
      "encode": { "...": "..." },
      "rerank": { "...": "..." }
    }
  }
}
```

If any step fails, the pipeline is aborted and the following response is returned:

```json
{
  "type": "inference",
  "uuid": "user-123",
  "payload": {
    "status": "FAILED",
    "model_name": "encoder",
    "data": "TritonInferenceFailed: error while running step 'encode'"
  }
}
```

### Reference Pydantic models

The following Pydantic models capture the expected schema for WebSocket messages.  
They are used as a lightweight reference for validation and tooling (envelope + common fields).
They are **not** a complete representation of every compatibility path described in this document
(for example: inference input normalization, optional alternate shapes, and pipeline-specific payloads).

```python
from classes.websocket.schemas import (
    AuthMessage,
    InfoMessage,
    ManagementMessage,
    InferenceMessage,
)
```

## Common Validation Failures

- Missing `uuid`, `type`, or `payload`
- `type` not in `auth`, `info`, `management`, `inference`
- First message not `auth`
- `uuid` mismatch after auth
- Deletion missing `vm_id` or `container_id`
- Inference missing `container_id`, `model_name`, or `inputs` (compat: `inputs` may be provided as `payload.inputs` and is mapped to `payload.request.inputs`)
- Inference missing `vm_ip` when it cannot be derived from the server's Docker cache using `container_id`
- Message larger than the configured `max_message_bytes` limit (defaults to 64 KiB) — returns an `error` message and closes the WebSocket with code `1009`.
