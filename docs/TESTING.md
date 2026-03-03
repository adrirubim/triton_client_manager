# Testing

Canonical source of truth for test execution and coverage.

---

## Table of Contents

- [Smoke Test](#smoke-test)
- [Regression Tests](#regression-tests)
- [Integration Tests (WebSocket)](#integration-tests-websocket)
- [Before Pushing](#before-pushing)

---

## Health checks

- `GET /health` — Liveness probe
- `GET /ready` — Readiness probe

## Smoke Test

| Field | Value |
|-------|-------|
| **File** | `MANAGER/tests/smoke_runtime.py` |
| **Purpose** | Runtime validation of core startup and WebSocket flow |

Uses mocks for OpenStack, Docker, Triton. Verifies:

- JobThread starts with correct dependency injection
- WebSocket server starts and accepts connections
- Auth with top-level `uuid` works
- Info `queue_stats` returns success
- Graceful shutdown completes cleanly

**Run:**

```bash
cd MANAGER
.venv/bin/python tests/smoke_runtime.py
```

**Output:** JSON with `startup`, `auth`, `info`; exit 0 on success.

**Not covered:** Real OpenStack, Docker, Triton; full creation/deletion; inference execution.

## Regression Tests

| Field | Value |
|-------|-------|
| **File** | `MANAGER/tests/test_regression.py` |
| **Purpose** | Unit tests for DI, contracts, config |

**Covers** (suite intenta verificar):

- JobInfo, JobManagement, JobInference constructor signatures
- Deletion payload normalization (flat and nested)
- Auth contract (top-level `uuid`)
- Inference example (vm_id en payload; ver [API_CONTRACTS.md](API_CONTRACTS.md))
- `inspect_config` ausente en advertised actions (test espera que esté removido)

**Known failures** (actualmente no pasan): `test_job_inference_instantiation`, `test_inference_example_uses_vm_ip`, `test_inspect_config_not_in_actions`.

**Run:**

```bash
cd MANAGER
.venv/bin/python -m unittest tests.test_regression -v
```

**Not covered:** Integration with real services; end-to-end creation/deletion; inference execution.

## Integration Tests (WebSocket)

| Field | Value |
|-------|-------|
| **File** | `MANAGER/tests/test_integration_ws.py` |
| **Purpose** | Multi-client WebSocket auth and info flow |

Requires: `pip install -r requirements-test.txt` (pytest, pytest-asyncio, websockets). The server is started automatically by a session-scoped fixture.

**Run:**

```bash
cd MANAGER
.venv/bin/pytest tests/test_integration_ws.py -v
```

**Alternative (standalone, no pytest):**

```bash
.venv/bin/python tests/smoke_runtime.py --with-ws-client
```

## Before Pushing

Full verification flow (recommended after upgrades or dependency changes):

```bash
cd MANAGER

# 1. Smoke with WebSocket client
.venv/bin/python tests/smoke_runtime.py --with-ws-client

# 2. Regression (unit tests)
.venv/bin/python -m unittest tests.test_regression -v

# 3. Integration (multi-client WebSocket)
.venv/bin/pip install -r requirements-test.txt
.venv/bin/pytest tests/test_integration_ws.py -v
```

4. Ensure all tests pass.

Continuous integration (for example, GitHub Actions) should run the regression suite on pull requests.
