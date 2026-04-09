#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "==> triton_client_manager – checks (CI parity)"

CHECK_LINT="${CHECK_LINT:-1}"
CHECK_COMPILE="${CHECK_COMPILE:-1}"
CHECK_TESTS="${CHECK_TESTS:-1}"
CHECK_SECURITY="${CHECK_SECURITY:-1}"

echo "==> 1/5 Verify repo standard"
chmod +x "$ROOT_DIR/scripts/verify-repo-standard.sh"
"$ROOT_DIR/scripts/verify-repo-standard.sh"

cd "$ROOT_DIR/apps/manager"

PYTHON_BIN="${PYTHON_BIN:-python3.12}"
PIP_BIN="${PIP_BIN:-pip}"

# Prefer project venv if present, otherwise use system python (CI uses system python).
if [[ -x "./.venv/bin/python" ]]; then
  PYTHON_BIN="./.venv/bin/python"
  PIP_BIN="./.venv/bin/pip"
fi

echo "==> Install dependencies (apps/manager)"
"$PYTHON_BIN" -m pip install --upgrade pip
"$PIP_BIN" install -r requirements.txt

if [[ "$CHECK_LINT" == "1" ]]; then
  echo "==> 2/5 Lint (apps/manager)"
  "$PYTHON_BIN" -m ruff check .
  "$PYTHON_BIN" -m black --check .
fi

if [[ "$CHECK_COMPILE" == "1" ]]; then
  echo "==> 3/5 Compile (apps/manager)"
  "$PYTHON_BIN" -m py_compile client_manager.py
  "$PYTHON_BIN" -m compileall -q classes utils
fi

if [[ "$CHECK_TESTS" == "1" ]]; then
  echo "==> 4/5 Tests (apps/manager)"
  "$PYTHON_BIN" -m pytest -q
fi

if [[ "$CHECK_SECURITY" == "1" ]]; then
  echo "==> 5/5 Security (pip-audit + bandit)"
  "$PYTHON_BIN" -m pip install -U pip-audit bandit
  "$PYTHON_BIN" -m pip_audit -r requirements.txt --ignore-vuln CVE-2026-28500
  "$PYTHON_BIN" -m bandit -c bandit.yaml -r classes utils client_manager.py
fi

echo "==> OK"

