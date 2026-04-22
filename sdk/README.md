# `tcm-client` SDK (WebSocket)

This SDK is the supported client for the Triton Client Manager WebSocket API.

It provides a typed, ergonomic interface for:
- authentication (`auth`)
- operational queries (`info.*`)
- management jobs (`management.*`)
- inference requests (`inference`)

## Connection

- WebSocket endpoint: `ws://<host>:<port>/ws`
- Health endpoints:
  - `GET /health` (liveness)
  - `GET /ready` (readiness)

`GET /ready` may return `503` with a sanitized payload if core dependencies are not healthy (or if the
probe itself fails). In that case, use `error_id` to correlate server logs:

```json
{
  "status": "not_ready",
  "reason": "readiness_probe_failed",
  "detail": "internal_error",
  "error_id": "..."
}
```

## Message envelope (wire contract)

All messages share the same top-level envelope:

```json
{
  "uuid": "client-uuid",
  "type": "auth|info|management|inference",
  "payload": {}
}
```

The server may also emit:

- `type="error"` for system-level conditions (including shutdown)

## Error handling model (v1.0.0-ULTIMATE)

The manager has two main error shapes you must handle:

### A) System-level errors (`type="error"`)
These represent conditions where the manager cannot or will not process work.

#### `SYSTEM_SHUTDOWN`
During shutdown draining (SIGTERM / deployment restarts), the manager explicitly NACKs queued/in-flight work:

```json
{
  "type": "error",
  "payload": {
    "code": "SYSTEM_SHUTDOWN",
    "message": "Manager is shutting down"
  }
}
```

**Client guidance**
- Treat as a stop-the-world signal: do not retry immediately.
- Close the socket and reconnect with backoff.
- Resume work only after `GET /ready` returns ready again.

### B) Inference job failures (`type="inference"`, `payload.status="FAILED"`)
Inference responses always come back as:

```json
{
  "type": "inference",
  "uuid": "client-uuid",
  "payload": {
    "status": "COMPLETED|FAILED",
    "model_name": "my-model",
    "data": {}
  }
}
```

When `status="FAILED"`, `payload.data` may be either:

1) A **typed Triton-facing error object** (recommended contract):

```json
{
  "code": "TRITON_TIMEOUT",
  "message": "[TritonThread] TRITON_TIMEOUT: model='my-model' retriable=True reason=Timeout",
  "retriable": true,
  "retry_after_seconds": 2
}
```

2) A **string** for validation/contract errors (missing fields, unknown container, etc.):

```json
"Missing required field 'vm_ip'"
```

**Client guidance**
- If `payload.data` is an object:
  - Use `code` + `retriable` to implement retry policy (do not parse `message`).
  - `TRITON_TIMEOUT` is retriable: retry with exponential backoff + jitter.
  - If `retry_after_seconds` is present, respect it.
- If `payload.data` is a string:
  - Treat as a client-side contract error (fix request formation).

## Admission Control (413 Payload Too Large)

If the manager is configured with a payload budget (e.g. `TCM_MAX_REQUEST_PAYLOAD_MB>0`),
requests that exceed the estimated decoded payload limit fail fast with an error reason containing:

`413 Payload Too Large`

Example failure reason:

```json
{
  "code": "TRITON_INFERENCE_FAILED",
  "message": "[TritonThread] TRITON_INFERENCE_FAILED: model='my-model' retriable=False reason=413 Payload Too Large: estimated_bytes=... limit_bytes=...",
  "retriable": false
}
```

**Client guidance**
- This is not retriable as-is. Reduce tensor dimensions / datatype size.

## Recommended retry policy (high-level)

- **System errors**
  - `SYSTEM_SHUTDOWN`: reconnect with backoff; wait for readiness
- **Retriable Triton errors** (`retriable=true`)
  - `TRITON_TIMEOUT`, `TRITON_NETWORK`, `TRITON_OVERLOADED`, `TRITON_CIRCUIT_OPEN`
  - retry with exponential backoff + jitter; cap max attempts
- **Fatal Triton errors** (`retriable=false`)
  - do not retry; fix request or intervene operationally (model/shape/config)

## Install

```bash
python -m pip install --upgrade pip
python -m pip install tcm-client
```

## Minimal usage example (Python)

```python
import asyncio

from tcm_client import AuthContext, TcmWebSocketClient


async def main() -> None:
    uri = "ws://127.0.0.1:8000/ws"

    ctx = AuthContext(
        uuid="client-1",
        token="opaque-or-jwt-token",
        sub="user-123",
        tenant_id="tenant-abc",
        roles=["inference"],
    )

    async with TcmWebSocketClient(uri, ctx) as client:
        await client.auth()

        # Example: call your inference helper (depends on SDK surface)
        # resp = await client.infer_http(...)
        # if resp.status == "FAILED": handle as described above


if __name__ == "__main__":
    asyncio.run(main())
```

## CLI

```bash
tcm-client-cli --uri "ws://127.0.0.1:8000/ws" queue-stats
```

