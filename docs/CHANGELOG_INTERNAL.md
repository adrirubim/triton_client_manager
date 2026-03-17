# Engineering Changelog

Engineering changelog for Triton Client Manager (non-marketing).

---

## Notable Changes

### Dependency Injection Fixes

| Component | Change |
|-----------|--------|
| **JobManagement** | Constructor order `(docker, triton, openstack, websocket, management_actions_available)` |
| **JobInference** | Constructor order updated to `(triton, docker, openstack, websocket)` and aligned with `JobThread` wiring (no extra config arguments) |
| **JobInfo** | Constructor fixed to `(docker, openstack, websocket, get_queue_stats)` — no extra arguments |

### Deletion Payload Normalization

- Deletion handler accepts flat or nested payloads
- Normalizes to `openstack.*` and `docker.*` for sub-handlers
- Extracts `vm_id`, `container_id`, `vm_ip` from top-level or nested structure

### Auth / Inference Contract Alignment

- Auth uses top-level `uuid` (not `payload.user_id`)
- Inference accepts payloads that identify the target instance via `container_id` + `vm_ip` (current handler validation), and also supports backwards-compatible shapes that provide `container_id` and omit `vm_ip` (deriving it from the known Docker container cache).
- Inference inputs are normalized for compatibility between:
  - manager internal format: `{name, dims, type, value}`
  - SDK-friendly format: `{name, shape, datatype, data}`

### Creation Rollback Fix

- `JobCreation` rollback: `delete_vm(vm_id)` passes string, not dict
- `delete_container` rollback: uses `worker_ip` (vm_ip) for Docker API

### Config Updates

- `info_actions_available` now includes `queue_stats` in `apps/manager/config/jobs.yaml` to match default schemas and test flows.

### Python 3.12 Compatibility

- Flavor dataclass: field order adjusted so `swap` (with default) is last

### WebSocket Startup and Shutdown

- Uvicorn lifespan initialized before `startup()` when using programmatic Server API
- Graceful shutdown via `server.should_exit = True` instead of `loop.stop()`
- Smoke test waits for WS thread via `ws.join(timeout=5)`

### Tests and CI

- Smoke runtime test: `tests/smoke_runtime.py`
- Regression suite: `tests/test_regression.py`
- CI: regression tests run on pull requests (e.g. via GitHub Actions)

### Metrics and Observability

- Introduced `utils/metrics.py` with Prometheus counters and gauges for WebSocket traffic and job queues/executors.
- Exposed `/metrics` endpoint in `WebSocketThread` (FastAPI) wired to `JobThread.get_queue_stats()` for queue/executor statistics.

