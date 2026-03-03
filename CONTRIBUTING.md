# Contributing to Triton Client Manager

---

## Table of Contents

- [Branch Workflow](#branch-workflow)
- [Validate Before Pushing](#validate-before-pushing)
- [Documentation Updates](#documentation-updates)
- [Merge Request Hygiene](#merge-request-hygiene)

---

## Branch Workflow

- Use feature branches for changes; merge via pull requests.
- Keep `master` (or main) deployable at all times.

## Validate Before Pushing

### 1. Smoke test

Runtime validation with mocks (JobThread, WebSocket, auth, info):

```bash
cd MANAGER
.venv/bin/python tests/smoke_runtime.py
```

### 2. Regression tests

Unit tests for DI, deletion, auth, inference, config:

```bash
cd MANAGER
.venv/bin/python -m unittest tests.test_regression -v
```

### 3. Full test suite (pytest)

```bash
cd MANAGER
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt
.venv/bin/pytest tests/ -v
```

### 4. Integration tests (WebSocket only)

Requires: `pip install -r requirements-test.txt` (pytest, pytest-asyncio, websockets).  
The server is started automatically by a session-scoped fixture:

```bash
cd MANAGER
.venv/bin/pytest tests/test_integration_ws.py -v
```

Alternative: `python tests/smoke_runtime.py --with-ws-client` (standalone, no pytest).

### 5. Compilation check

```bash
cd MANAGER
python -m py_compile client_manager.py
python -m compileall -q classes utils
```

Continuous integration should run at least the regression suite and a subset of pytest on pull requests. Smoke and integration tests are recommended locally before pushing.

## Upgrade Dependencies

To update all packages to latest stable:

```bash
cd MANAGER
.venv/bin/pip install -r requirements.txt -r requirements-test.txt --upgrade
```

Run smoke and regression tests afterward to verify.

## Documentation Updates

- Update `docs/` when changing architecture, API contracts, configuration, or operations.
- Update [docs/CHANGELOG_INTERNAL.md](docs/CHANGELOG_INTERNAL.md) for notable internal changes.
- Keep [MANAGER/README.md](MANAGER/README.md) as a slim quick-start; move detailed content to `docs/`.

## Pull Request Hygiene

- Summarize scope, areas touched, and validation performed.
- Reference related issues when applicable.
- Ensure CI passes before requesting review.
