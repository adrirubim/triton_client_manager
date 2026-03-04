# Troubleshooting

Common issues and fixes for Triton Client Manager.

---

## Table of Contents

- [Wrong Working Directory](#wrong-working-directory)
- [Missing Virtual Environment](#missing-virtual-environment)
- [PEP 668 / externally-managed-environment](#pep-668--externally-managed-environment)
- [Missing Python Packages](#missing-python-packages)
- [Python 3.12 Dataclass Field Order](#python-312-dataclass-field-order)
- [Constructor Mismatches](#constructor-mismatches)
- [Uvicorn Lifespan / Startup](#uvicorn-lifespan--startup)
- [Graceful Shutdown Issues](#graceful-shutdown-issues)
- [Auth Payload Mismatch](#auth-payload-mismatch)
- [Deletion Payload Mismatch](#deletion-payload-mismatch)
- [OpenStack Unavailable](#openstack-unavailable-during-full-startup)

---

## Wrong Working Directory

**Symptom:** `FileNotFoundError` for `config/jobs.yaml` or similar.

**Fix:** Run from `MANAGER`:

```bash
cd MANAGER
python client_manager.py
```

## Missing Virtual Environment

**Symptom:** `ModuleNotFoundError` for fastapi, uvicorn, etc.

**Fix:** Create and activate venv:

```bash
cd MANAGER
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## PEP 668 / externally-managed-environment

**Symptom:** `pip install -r requirements.txt` fails with "externally managed environment".

**Fix:** Use a virtual environment; do not use `--break-system-packages`. On Debian/Ubuntu, install `python3-venv` if needed:

```bash
sudo apt install python3.12-venv
```

## Missing Python Packages

**Symptom:** Import errors for `websockets`, `yaml`, etc.

**Fix:** Install dependencies in the venv:

```bash
cd MANAGER
source .venv/bin/activate
pip install -r requirements.txt
```

If you use `tests/ws_client_test.py` or `_______WEBSOCKET/client.py`, add: `pip install websockets` (not in requirements.txt).

## Python 3.12 Dataclass Field Order

**Symptom:** `TypeError: non-default argument 'vcpus' follows default argument` in Flavor or similar.

**Fix:** In dataclasses, fields without defaults must come before fields with defaults. Put optional fields last.

## Constructor Mismatches

**Symptom:** `TypeError: ... takes N positional arguments but M were given`.

**Fix:** Ensure constructor signatures match call sites:

| Handler | Constructor (as called by JobThread) | Note |
|---------|--------------------------------------|------|
| JobInfo | `(docker, openstack, websocket, get_queue_stats)` | |
| JobManagement | `(docker, triton, openstack, websocket, management_actions_available=...)` | |
| JobInference | `(triton, docker, openstack, websocket, inference_actions_available)` | |

If you see mismatches, check that the constructor definitions in the corresponding classes match these signatures. See [ARCHITECTURE.md](ARCHITECTURE.md) for the full dependency injection map.

## Uvicorn Lifespan / Startup

**Symptom:** `'Server' object has no attribute 'lifespan'` or similar.

**Fix:** WebSocketThread uses uvicorn programmatically; `Server.lifespan` is set in `_serve()` not `__init__`. The code initializes `server.lifespan` before `startup()`. Ensure uvicorn is `>=0.30.0` (see [VERSION_STACK.md](VERSION_STACK.md)).

## Graceful Shutdown Issues

**Symptom:** "Event loop stopped before Future completed" or "Task was destroyed but it is pending".

**Fix:** WebSocketThread must use `server.should_exit = True` for graceful shutdown, not `loop.stop()`. Clients are closed first; then the server exits its main loop and runs `shutdown()`.

## Auth Payload Mismatch

**Symptom:** Auth rejected; "First message must be type 'auth'".

**Fix:** First message must be:

```json
{"type": "auth", "uuid": "client-id", "payload": {}}
```

Use top-level `uuid`, not `payload.user_id`.

## Deletion Payload Mismatch

**Symptom:** "Deletion requires vm_id and container_id".

**Fix:** Provide `vm_id` and `container_id` at top level or under `openstack.vm_id` and `docker.container_id`. See [API_CONTRACTS.md](API_CONTRACTS.md).

## OpenStack Unavailable During Full Startup

**Symptom:** OpenStack thread fails to initialize; `TimeoutError`.

**Fix:** Ensure OpenStack API is reachable and credentials in `config/openstack.yaml` are correct. For local validation without OpenStack, use the smoke test (mocks).

## Metrics and Observability Issues

**Symptom:** `/metrics` endpoint returns only zeros or fails intermittently.

**Fix:**

- `/metrics` pulls queue/executor stats via `JobThread.get_queue_stats()`. If stats collection raises, the endpoint falls back to empty values but still returns `200`.
- Check that `JobThread` is running and that `WebSocketThread` was started with `get_queue_stats` wired in `ClientManager.setup()`.
- Use logs (with `client_uuid`, `job_id`, `job_type`) together with metrics gauges (`tcm_queue_*`, `tcm_executor_*`, `tcm_ws_*`) to correlate traffic, backpressure and failures.
