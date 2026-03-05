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
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt
.venv/bin/python tests/smoke_runtime.py
```

**Output:** JSON with `startup`, `auth`, `info`; exit 0 on success.

**Not covered:** Real OpenStack, Docker, Triton; full creation/deletion; inference execution.

## Regression Tests

| Field | Value |
|-------|-------|
| **File** | `MANAGER/tests/test_regression.py` |
| **Purpose** | Unit tests for DI, contracts, config |

**Covers** (the suite aims to verify):

- JobInfo, JobManagement, JobInference constructor signatures
- Deletion payload normalization (flat and nested)
- Auth contract (top-level `uuid`)
-- Inference example (`vm_id` in payload; see [API_CONTRACTS.md](API_CONTRACTS.md))
-- `inspect_config` absent from advertised actions (test expects it to be removed)

**Known failures** (historical, may no longer apply): `test_job_inference_instantiation`, `test_inference_example_uses_vm_ip`, `test_inspect_config_not_in_actions`.

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

Requires: `pip install -r requirements-test.txt` (pytest, pytest-asyncio, websockets, httpx). The server is started automatically by a session-scoped fixture.

**Run:**

```bash
cd MANAGER
.venv/bin/pytest tests/test_integration_ws.py -v
```

**Alternative (standalone, no pytest):**

```bash
.venv/bin/python tests/smoke_runtime.py --with-ws-client
```

## Security logging

Minimal automated check to ensure that sensitive values in payloads are **not**
leaked into logs under backpressure scenarios (`info`, `management`,
`inference` queues llenas):

```bash
cd MANAGER
. .venv/bin/activate
python -m pytest tests/test_security_logging.py -v
```

This suite (`tests/test_security_logging.py`) uses synthetic "secrets" in the
payload and asserts that they never appear in log messages emitted by
`JobThread` when queues are full.

## Coverage

To run the full pytest suite with coverage over the core modules (`classes`, `utils`, `client_manager`) and see a terminal summary:

```bash
cd MANAGER
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt

.venv/bin/pytest --cov=classes --cov=utils --cov=client_manager --cov-report=term-missing
```

To generate an HTML coverage report (written to `MANAGER/htmlcov/index.html`):

```bash
cd MANAGER
source .venv/bin/activate

.venv/bin/pytest --cov=classes --cov=utils --cov=client_manager --cov-report=html
```

## Linting (Ruff + Black)

CI runs **Ruff** and **Black** on every push and pull request. You should run the same checks locally:

```bash
cd MANAGER
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt

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
cd MANAGER
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt

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
