# Runbook

Operations and deployment guidance for Triton Client Manager.

---

## Table of Contents

- [Working Directory](#working-directory)
- [Local Setup](#local-setup)
- [Run Application](#run-application)
- [Smoke Test](#smoke-test)
- [Regression Tests](#regression-tests)
- [Startup Assumptions](#startup-assumptions)
- [Pre-Push Validation](#pre-push-validation)

---

## Working Directory

Run all commands from `MANAGER` or ensure the current working directory is `MANAGER` when starting the application. `client_manager.py` loads `config/*.yaml` relative to the current directory.

## Local Setup

```bash
cd MANAGER
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

> **Note:** On Ubuntu/WSL (PEP 668), system-wide `pip install` may fail; use a virtual environment. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md).

## Run Application

```bash
cd MANAGER
python client_manager.py
```

Threads start in order: OpenStack → Triton → Docker → Job → WebSocket. Each must report ready within 30 seconds or startup fails with `TimeoutError`.

## Smoke Test

Uses mocks for OpenStack, Docker, Triton. Validates JobThread DI, WebSocket auth, and info `queue_stats`.

```bash
cd MANAGER
.venv/bin/python tests/smoke_runtime.py
```

**Expected output:** `{"startup": true, "auth": true, "info": true}` (exit 0).

## Regression Tests

Unit tests for DI, deletion normalization, auth contract, inference example, config.

```bash
cd MANAGER
.venv/bin/python -m unittest tests.test_regression -v
```

## Startup Assumptions

| Requirement | Notes |
|-------------|-------|
| OpenStack API | Reachable for full startup |
| Docker API | Reachable |
| Triton | Health checks run against registered servers |
| Config files | Present in `config/` |

With mocks (smoke test), OpenStack/Docker/Triton are not required.

## Pre-Push Validation

1. `cd MANAGER && .venv/bin/python tests/smoke_runtime.py`
2. `cd MANAGER && .venv/bin/python -m unittest tests.test_regression -v`
3. `cd MANAGER && python -m py_compile client_manager.py`
4. `cd MANAGER && python -m compileall -q classes utils`

CI pipelines (for example, GitHub Actions) should at minimum run the regression suite on pull requests.
