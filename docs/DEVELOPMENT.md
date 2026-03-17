# Development

Canonical developer workflow for Triton Client Manager.

This repository runs on Ubuntu/WSL with **PEP 668**, so you must use a virtual environment.

---

## One-time setup (create venv + install deps)

```bash
cd apps/manager
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r requirements.txt -r requirements-test.txt

# Install the SDK in editable mode (mirrors CI contract tests)
pip install -e ../../sdk
```

Notes:

- Keep the venv **only** in `apps/manager/.venv`. Do not create a second venv at the repository root.
- If you see `externally-managed-environment`, you are trying to run `pip` outside the venv.
- Optional: offline model tooling (ONNX inspection) is not required for runtime.
  Install only when needed:

```bash
cd apps/manager
source .venv/bin/activate
pip install -r requirements-model-tools.txt
```

---

## Daily workflow

### Run dev server (mocked backends)

```bash
cd apps/manager
source .venv/bin/activate
.venv/bin/python dev_server.py
```

### Run full manager (real backends required)

```bash
cd apps/manager
source .venv/bin/activate
python client_manager.py
```

---

## Validation (same shape as CI)

```bash
cd apps/manager
source .venv/bin/activate

python -m py_compile client_manager.py
python -m compileall -q classes utils

python tests/smoke_runtime.py --with-ws-client
python -m unittest tests.test_regression -v
pytest tests/ -v

ruff check .
black --check .
```

---

## Dependency upgrades (safe approach)

This project has real constraints (for example `tcm-client` pins `websockets<13`, and `tritonclient` constrains gRPC/protobuf). Treat `pip list --outdated` as informational.

Recommended:

```bash
cd apps/manager
source .venv/bin/activate

pip install -U -r requirements.txt -r requirements-test.txt
pip install -e ../../sdk

python -m pip check
python -m pip list --outdated
```

