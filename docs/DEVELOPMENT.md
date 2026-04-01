# Development

Canonical developer workflow for Triton Client Manager.

This repository runs on Ubuntu/WSL with **PEP 668**, so you must use a virtual environment.

---

## One-time setup (create venv + install deps)

```bash
cd /var/www/triton_client_manager
python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -r apps/manager/requirements.txt

# Optional: install the SDK in editable mode
pip install -e ./sdk
```

Notes:

- The recommended venv location for this monorepo is **repo root**: `.venv/`.
- Avoid keeping two separate active venvs (for example a second venv under `apps/manager/.venv`) to prevent drift in installed deps.
- If you see `externally-managed-environment`, you are trying to run `pip` outside the venv.
- Optional: offline model tooling (ONNX inspection) is not required for runtime.
  Install only when needed:

```bash
cd /var/www/triton_client_manager
source .venv/bin/activate
pip install -r apps/manager/requirements-model-tools.txt
```

---

## Daily workflow

### Run dev server (mocked backends)

```bash
cd /var/www/triton_client_manager/apps/manager
source .venv/bin/activate
python dev_server.py
```

### Run full manager (real backends required)

```bash
cd /var/www/triton_client_manager/apps/manager
source .venv/bin/activate
python client_manager.py
```

---

## Validation (same shape as CI)

```bash
cd /var/www/triton_client_manager/apps/manager
source .venv/bin/activate

python -m py_compile client_manager.py
python -m compileall -q classes utils

python tests/smoke_runtime.py --with-ws-client
python -m unittest tests.test_regression -v
python -m pytest tests/ -v

ruff check .
black --check .
```

---

## Dependency upgrades (safe approach)

This project has real constraints (for example `tcm-client` pins `websockets<13`, and `tritonclient` constrains gRPC/protobuf). Treat `pip list --outdated` as informational.

Recommended:

```bash
cd /var/www/triton_client_manager
source .venv/bin/activate

pip install -U -r apps/manager/requirements.txt
pip install -e ./sdk

python -m pip check
python -m pip list --outdated
```

