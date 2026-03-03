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

**Required fields:** `vm_id`, `container_id`, `model_name`, `inputs`

Inference routes by `vm_id` and `container_id` (matches Triton server registration). Optional: `vm_ip` for handlers that use it; `request.inputs` for nested structure.

**Request:**

```json
{
  "type": "inference",
  "uuid": "user-123",
  "payload": {
    "vm_id": "openstack-vm-uuid",
    "container_id": "docker-container-id",
    "model_name": "my-model-name",
    "inputs": [{"name": "input_0", "type": "TYPE_FP32", "dims": 4, "value": [1.0, 2.0, 3.0, 4.0]}]
  }
}
```

**Protocol:** `payload.request.protocol` (`grpc` or `http`); default `http`.

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
- Message larger than the configured `max_message_bytes` limit (defaults to 64 KiB), returns an `error` message and closes the WebSocket with code `1009`.
