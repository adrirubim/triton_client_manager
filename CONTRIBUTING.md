# Contributing to Triton Client Manager

Thank you for your interest in contributing to this project. Please read this guide and the main [README](README.md) before opening pull requests.

---

## Branching and Workflow

- Work on **feature branches**; merge changes via pull requests.
- Keep `main` deployable at all times.
- Use clear branch names: `feat/...`, `fix/...`, `docs/...`.

---

## Local Validation (Before Pushing)

Always validate locally with the same steps that CI will run.

> **Prerequisite:** complete the one-time setup in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
> so `apps/manager/.venv` exists and dependencies are installed.


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
source .venv/bin/activate
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

### 6. Integration tests with real backends (optional / CI nightly)

For teams with access to **real OpenStack/Docker/Triton backends**, there is an additional pytest module and workflow:

- File: [apps/manager/tests/test_integration_backends.py](apps/manager/tests/test_integration_backends.py)
- Workflow: [.github/workflows/integration-backends.yml](.github/workflows/integration-backends.yml)

By default these tests are **skipped**. They only run when:

- `TCM_RUN_REAL_BACKENDS=1` is defined in the environment, and
- the environment variables `TCM_REAL_MANAGER_WS_URL` and `TCM_REAL_MODEL_NAME` are set (and, if applicable, a real auth token).

To run locally:

```bash
cd apps/manager
export TCM_RUN_REAL_BACKENDS=1
.venv/bin/pytest tests/test_integration_backends.py -v
```

See `docs/TESTING.md` for details and recommended usage in CI.

---

## Dependencies

To update all packages to the latest stable versions:

```bash
cd apps/manager
source .venv/bin/activate
.venv/bin/pip install -r requirements.txt -r requirements-test.txt --upgrade
```

Run smoke and regression tests afterward to verify.

---

## Linting and Formatting

Before opening a pull request, run the same linters that CI uses:

```bash
cd apps/manager
.venv/bin/ruff check .
.venv/bin/black .
```

Fix any reported issues before pushing.

---

## Documentation

- Update [`docs/`](docs/) when changing architecture, API contracts, configuration, or operations.
- Keep internal-only notes out of public docs.
- Keep [`apps/manager/README.md`](apps/manager/README.md) as a slim quick-start; move detailed content to `docs/`.

---

## Pull Requests

- Open a pull request against the appropriate base branch (usually `main`).
- Summarize scope, areas touched, and validation performed.
- Ensure all tests and linters pass; CI must be green before merge.
- Reference related issues when applicable (for example, `Fixes #123`).

---

## Questions

- For questions or coordination, contact the maintainer (see [README](README.md) → Author).
