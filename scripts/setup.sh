#!/usr/bin/env bash
# Setup script for Triton Client Manager
# Run from project root: ./scripts/setup.sh

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANAGER="$ROOT/apps/manager"

echo "[setup] Project root: $ROOT"
echo "[setup] Application dir: $MANAGER"

# Create venv in repo root (canonical)
cd "$ROOT"
if [ ! -d ".venv" ]; then
  echo "[setup] Creating .venv in repo root..."
  python3 -m venv .venv
  echo "[setup] venv created."
else
  echo "[setup] .venv already exists in repo root."
fi

# Activate and install
echo "[setup] Installing dependencies..."
.venv/bin/pip install --quiet -r apps/manager/requirements.txt
.venv/bin/pip install --quiet -e ./sdk
echo "[setup] Dependencies installed."

# Smoke test
echo "[setup] Running smoke test..."
cd "$MANAGER"
PYTHONPATH=. "$ROOT/.venv/bin/python" tests/smoke_runtime.py --with-ws-client
echo "[setup] ✓ Setup complete. Run: cd apps/manager && source ../../.venv/bin/activate && python client_manager.py"
