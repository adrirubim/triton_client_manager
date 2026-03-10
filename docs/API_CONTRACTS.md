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

Validation failures return `{"type": "error", "payload": {"message": "..."}}`.

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
    "openstack": {"vm_ip": "x.x.x.x", "vm_id": "openstack-vm-uuid"},
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
    "vm_ip": "10.0.0.1"
  }
}
```

## Inference

### Single-model inference

**Required fields:** `vm_id`, `container_id`, `model_name`, `inputs`

Inference routes by `vm_id` and `container_id` (matches Triton server registration). Optional: `vm_ip` for handlers that use it; `request.protocol` to select HTTP/gRPC.

**Request:**

```json
{
  "type": "inference",
  "uuid": "user-123",
  "payload": {
    "vm_id": "openstack-vm-uuid",
    "container_id": "docker-container-id",
    "model_name": "my-model-name",
    "inputs": [
      {
        "name": "input_0",
        "type": "TYPE_FP32",
        "dims": 4,
        "value": [1.0, 2.0, 3.0, 4.0]
      }
    ],
    "request": {
      "protocol": "http"
    }
  }
}
```

**Protocol:** `payload.request.protocol` (`grpc` or `http`); default `http`.

### Pipeline (multi‑model, HTTP)

For simple, sequential multi‑model pipelines (A → B → C) sobre la **misma instancia** (`vm_id` /
`container_id` y su `vm_ip` asociada), el `payload` admite una clave `pipeline`:

```json
{
  "type": "inference",
  "uuid": "user-123",
  "payload": {
    "vm_id": "openstack-vm-uuid",
    "container_id": "docker-container-id",
    "vm_ip": "10.0.0.1",
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

Notas:

- Todos los pasos del pipeline comparten `vm_id`, `container_id` **y** `vm_ip`, que deben apuntar a la misma instancia Docker registrada.
- Cada paso debe aportar sus propios `inputs`; el servidor no infiere
  automáticamente tipos ni formas a partir de la salida de pasos anteriores.
- El campo `name` se utiliza como clave en la respuesta agregada; si se omite,
  se usa `model_name`.

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

En caso de error en alguno de los pasos, el pipeline se aborta y se devuelve:

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
They are used as a reference for validation and tooling:

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
- Inference missing `vm_id`, `container_id`, `model_name`, or `inputs`
- Message larger than the configured `max_message_bytes` limit (defaults to 64 KiB) — returns an `error` message and closes the WebSocket with code `1009`.
