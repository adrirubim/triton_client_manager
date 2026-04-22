#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'EOF'
test_suite_master.sh — Triton Client Manager (v2.0.0-GOLDEN) Day‑2 validation runner

Usage:
  bash ./test_suite_master.sh --unit
  bash ./test_suite_master.sh --smoke
  bash ./test_suite_master.sh --full

Modes:
  --unit   Run pytest only (apps/manager)
  --smoke  Run the runtime smoke test (apps/manager/tests/smoke_runtime.py)
  --full   CI parity runner (delegates to scripts/check.sh)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" || "${#}" -eq 0 ]]; then
  usage
  exit 0
fi

MODE="${1:-}"

case "$MODE" in
  --unit)
    cd "$ROOT_DIR/apps/manager"
    if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
      PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
    else
      PYTHON_BIN="${PYTHON_BIN:-python3}"
    fi
    echo "==> [unit] pytest (apps/manager)"
    "$PYTHON_BIN" -m pytest -q
    ;;

  --smoke)
    cd "$ROOT_DIR/apps/manager"
    if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
      PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
    else
      PYTHON_BIN="${PYTHON_BIN:-python3}"
    fi
    echo "==> [smoke] smoke_runtime.py --with-ws-client"
    PYTHONPATH=. "$PYTHON_BIN" tests/smoke_runtime.py --with-ws-client
    ;;

  --full)
    echo "==> [full] scripts/check.sh (CI parity)"
    chmod +x "$ROOT_DIR/scripts/check.sh"
    "$ROOT_DIR/scripts/check.sh"
    ;;

  *)
    echo "Unknown mode: $MODE" >&2
    usage >&2
    exit 2
    ;;
esac

echo "==> OK"

