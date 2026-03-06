#!/usr/bin/env bash
# Setup script for Triton Client Manager
# Run from project root: ./scripts/setup.sh

set -e
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANAGER="$ROOT/apps/manager"

echo "[setup] Project root: $ROOT"
echo "[setup] Application dir: $MANAGER"

# Remove .venv from root if it exists (wrong location)
if [ -d "$ROOT/.venv" ]; then
  echo "[setup] Removing .venv from root (incorrect location)..."
  rm -rf "$ROOT/.venv"
  echo "[setup] Done. venv must be inside apps/manager/."
fi

# Create venv in apps/manager
cd "$MANAGER"
if [ ! -d ".venv" ]; then
  echo "[setup] Creating .venv in apps/manager..."
  python3 -m venv .venv
  echo "[setup] venv created."
else
  echo "[setup] .venv already exists in apps/manager."
fi

# Activate and install
echo "[setup] Installing dependencies..."
.venv/bin/pip install --quiet -r requirements.txt
echo "[setup] Dependencies installed."

# Smoke test
echo "[setup] Running smoke test..."
.venv/bin/python tests/smoke_runtime.py
echo "[setup] ✓ Setup complete. Run: cd apps/manager && source .venv/bin/activate && python client_manager.py"
