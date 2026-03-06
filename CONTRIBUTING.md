# Contributing to Triton Client Manager

Thank you for your interest in contributing to this project. Please read this guide and the main `README` before opening pull requests.

---

## Branching and Workflow

- Work on **feature branches**; merge changes via pull requests.
- Keep `main` deployable at all times.
- Use clear branch names: `feat/...`, `fix/...`, `docs/...`.

---

## Local Validation (Before Pushing)

Always validate locally with the same steps that CI will run.

### 1. Smoke test

Runtime validation with mocks (JobThread, WebSocket, auth, info):

```bash
cd apps/manager
.venv/bin/python tests/smoke_runtime.py
```

### 2. Regression tests

Unit tests for DI, deletion, auth, inference, and config:

```bash
cd apps/manager
.venv/bin/python -m unittest tests.test_regression -v
```

### 3. Full test suite (pytest)

```bash
cd apps/manager
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-test.txt
.venv/bin/pytest tests/ -v
```

### 4. Integration tests (WebSocket only)

Requires: `pip install -r requirements-test.txt` (pytest, pytest-asyncio, websockets).  
The server is started automatically by a session-scoped fixture:

```bash
cd apps/manager
.venv/bin/pytest tests/test_integration_ws.py -v
```

Alternative: `python tests/smoke_runtime.py --with-ws-client` (standalone, no pytest).

### 5. Compilation check

```bash
cd apps/manager
.venv/bin/python -m py_compile client_manager.py
.venv/bin/python -m compileall -q classes utils
```

Continuous integration should run at least the regression suite and a subset of pytest on pull requests. Smoke and integration tests are recommended locally before pushing.

---

## Dependencies

To update all packages to the latest stable versions:

```bash
cd apps/manager
.venv/bin/pip install -r requirements.txt -r requirements-test.txt --upgrade
```

Run smoke and regression tests afterward to verify.

---

## Documentation

- Update `docs/` when changing architecture, API contracts, configuration, or operations.
- Update `docs/CHANGELOG_INTERNAL.md` for notable internal changes.
- Keep `apps/manager/README.md` as a slim quick-start; move detailed content to `docs/`.

---

## Pull Requests

- Open a pull request against the appropriate base branch (usually `main`).
- Summarize scope, areas touched, and validation performed.
- Ensure all tests and linters pass; CI must be green before merge.
- Reference related issues when applicable (for example, `Fixes #123`).

---

## Questions

- For questions or coordination, contact the maintainer (see `README` → Author).
