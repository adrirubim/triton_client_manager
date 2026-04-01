# Testing

Canonical source of truth for test execution and coverage.

---

## Table of Contents

- [Smoke Test](#smoke-test)
- [Regression Tests](#regression-tests)
- [Integration Tests (WebSocket)](#integration-tests-websocket)
- [Coverage](#coverage)
- [Linting (Ruff + Black)](#linting-ruff--black)
- [Before Pushing](#before-pushing)

---

## Health checks

- `GET /health` — Liveness probe
- `GET /ready` — Readiness probe

> **Prerequisite:** complete the one-time setup in [DEVELOPMENT.md](DEVELOPMENT.md) so
> `apps/manager/.venv` exists and dependencies are installed.

## Smoke Test

| Field | Value |
|-------|-------|
| **File** | `apps/manager/tests/smoke_runtime.py` |
| **Purpose** | Runtime validation of core startup and WebSocket flow |

Uses mocks for OpenStack, Docker, Triton. Verifies:

- JobThread starts with correct dependency injection
- WebSocket server starts and accepts connections
- Auth with top-level `uuid` works
- Info `queue_stats` returns success
- Graceful shutdown completes cleanly

**Run:**

```bash
cd apps/manager
source .venv/bin/activate

.venv/bin/python tests/smoke_runtime.py
```

**Output:** JSON with `startup`, `auth`, `info`; exit 0 on success.

**Not covered:** Real OpenStack, Docker, Triton; full creation/deletion; inference execution.

## Regression Tests

| Field | Value |
|-------|-------|
| **File** | `apps/manager/tests/test_regression.py` |
| **Purpose** | Unit tests for DI, contracts, config |

**Covers** (the suite aims to verify):

- JobInfo, JobManagement, JobInference constructor signatures
- Deletion payload normalization (flat and nested)
- Auth contract (top-level `uuid`)
-- Inference example (`vm_id` in payload; see [API_CONTRACTS.md](API_CONTRACTS.md))
-- `inspect_config` absent from advertised actions (test expects it to be removed)

As of March 2026, the regression suite is expected to be **fully green**.  
Historically, the tests `test_job_inference_instantiation`, `test_inference_example_uses_vm_ip`, and `test_inspect_config_not_in_actions` caught specific regressions, but they are now part of the normal guardrail: **any failure in these tests should be treated as a bug to fix, not as an accepted “known failure”**.

**Run:**

```bash
cd apps/manager
.venv/bin/python -m unittest tests.test_regression -v
```

**Not covered:** Integration with real services; end-to-end creation/deletion; inference execution.

## Integration Tests (WebSocket)

| Field | Value |
|-------|-------|
| **File** | `apps/manager/tests/test_integration_ws.py` |
| **Purpose** | Multi-client WebSocket auth and info flow |

Requires: `pip install -r requirements-test.txt` (pytest, pytest-asyncio, websockets, httpx). The server is started automatically by a session-scoped fixture.

**Run:**

```bash
cd apps/manager
.venv/bin/pytest tests/test_integration_ws.py -v
```

**Alternative (standalone, no pytest):**

```bash
.venv/bin/python tests/smoke_runtime.py --with-ws-client
```

## Integration tests with real backends (advanced / CI nightly)

For environments where **real OpenStack/Docker/Triton backends** are available, a
dedicated pytest module and CI workflow exist:

- **File**: `apps/manager/tests/test_integration_backends.py`
- **Workflow**: `.github/workflows/integration-backends.yml`

By default, these tests are **skipped**. They only run when the environment
variable `TCM_RUN_REAL_BACKENDS=1` is present (for example, configured as a
`secret`/env in the runner that has access to the real backends).

**Run locally (when you have real backends wired):**

```bash
cd apps/manager
export TCM_RUN_REAL_BACKENDS=1
.venv/bin/pytest tests/test_integration_backends.py -v
```

In a production‑like CI environment, the workflow `Integration Backends (nightly)`
can be enabled to run nightly or on demand via `workflow_dispatch`. Teams with
real infrastructure are expected to extend `test_integration_backends.py` to run
full creation → inference → teardown flows and error scenarios.

## Using `tcm-client-cli` in CI and local smoke tests

The Python SDK `tcm-client` includes a small CLI, `tcm-client-cli`, that can be
used for:

- simple smoke tests (`auth` + `info.queue_stats`);
- lightweight load tests feeding `/metrics`;
- manual management and inference flows driven by JSON payloads.

Typical usage:

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

In CI, you can add an extra, fast validation step before running the full test
suite, for example:

```bash
python -m pip install tcm-client
tcm-client-cli queue-stats --repeat 10 --concurrency 2
```

This sends a small number of `info.queue_stats` requests and exercises both the
WebSocket path and the metrics pipeline without requiring the full regression
suite.

## Security logging

Minimal automated check to ensure that sensitive values in payloads are **not**
leaked into logs under backpressure scenarios (`info`, `management`,
`inference` queues full):

```bash
cd apps/manager
source .venv/bin/activate
python -m pytest tests/test_security_logging.py -v
```

This suite (`tests/test_security_logging.py`) uses synthetic "secrets" in the
payload and asserts that they never appear in log messages emitted by
`JobThread` when queues are full.

## Coverage

To run the full pytest suite with coverage over the core modules (`classes`, `utils`, `client_manager`) and see a terminal summary:

```bash
cd apps/manager
source .venv/bin/activate

# One-time (only if deps are not installed yet):
# pip install -r requirements.txt -r requirements-test.txt
# pip install -e ../../sdk

.venv/bin/pytest --cov=classes --cov=utils --cov=client_manager --cov-report=term-missing
```

To generate an HTML coverage report (written to `apps/manager/htmlcov/index.html`):

```bash
cd apps/manager
source .venv/bin/activate

.venv/bin/pytest --cov=classes --cov=utils --cov=client_manager --cov-report=html
```

## Linting (Ruff + Black)

CI runs **Ruff** and **Black** on every push and pull request. You should run the same checks locally:

```bash
cd apps/manager
source .venv/bin/activate

# One-time (only if deps are not installed yet):
# pip install -r requirements.txt -r requirements-test.txt
# pip install -e ../../sdk

# Auto-format (Black) and autofix (Ruff)
black .
ruff check . --fix

# Verify everything is clean
ruff check .
black --check .
```

These tools come from `requirements-test.txt` and are required for CI to pass.

## Before Pushing

Full verification flow (recommended after upgrades or dependency changes):

```bash
cd apps/manager
source .venv/bin/activate

# One-time (only if deps are not installed yet):
# pip install -r requirements.txt -r requirements-test.txt
# pip install -e ../../sdk

# 1. Lint & format
black .
ruff check . --fix
ruff check .
black --check .

# 2. Smoke with WebSocket client
.venv/bin/python tests/smoke_runtime.py --with-ws-client

# 3. Full pytest suite
.venv/bin/pytest tests/ -v

# 4. Regression (optional if pytest is already green)
.venv/bin/python -m unittest tests.test_regression -v
```

Ensure all tests pass locally before pushing.

Continuous integration (for example, GitHub Actions) runs:

- `pip install -r requirements.txt -r requirements-test.txt`
- `ruff check .`
- `black --check .`
- smoke + regression tests
- full or partial pytest suite on pull requests.
