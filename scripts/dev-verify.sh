#!/usr/bin/env bash
set -euo pipefail

echo "==> triton_client_manager – local quality gate (CI parity)"

echo "==> 1/4 Lint / format"
cd apps/manager
if [[ -z "${VIRTUAL_ENV:-}" ]]; then
  # Repo standard venv lives at the repository root (../../.venv from here).
  source ../../.venv/bin/activate
fi
ruff check .
black --check .

echo "==> 2/4 Compile"
python -m py_compile client_manager.py
python -m compileall -q classes utils

echo "==> 3/4 Smoke runtime (with ws client)"
PYTHONPATH=. python tests/smoke_runtime.py --with-ws-client

echo "==> 4/4 Full tests"
PYTHONPATH=. python -m unittest discover -s tests -p "test_regression.py" -v
PYTHONPATH=. python -m pytest tests/ -q

echo "==> Quality gate completed successfully."

