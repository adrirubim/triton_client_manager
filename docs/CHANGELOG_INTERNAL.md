# Internal Changelog

Engineering changelog for Triton Client Manager. Not for product marketing.

---

## Notable Changes

### Dependency Injection Fixes

| Component | Change |
|-----------|--------|
| **JobManagement** | Constructor order `(docker, triton, openstack, websocket, management_actions_available)` |
| **JobInference** | Constructor order `(docker, openstack, websocket, inference_actions_available, triton)` |
| **JobInfo** | Constructor fixed to `(docker, openstack, websocket, get_queue_stats)` — no extra arguments |

### Deletion Payload Normalization

- Deletion handler accepts flat or nested payloads
- Normalizes to `openstack.*` and `docker.*` for sub-handlers
- Extracts `vm_id`, `container_id`, `vm_ip` from top-level or nested structure

### Auth / Inference Contract Alignment

- Auth uses top-level `uuid` (not `payload.user_id`)
- Inference uses `vm_id` and `container_id` for routing (matches Triton server registration)
- `payload_examples/inference.json` uses `vm_id`

### Creation Rollback Fix

- `JobCreation` rollback: `delete_vm(vm_id)` passes string, not dict
- `delete_container` rollback: uses `worker_ip` (vm_ip) for Docker API

### Config Updates

- `inspect_config` in `management_actions_available` in jobs.yaml; regression test `test_inspect_config_not_in_actions` expects it removed — known inconsistency

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
