#!/usr/bin/env bash
set -Eeuo pipefail

# Master Test Runner for triton_client_manager (WSL Bash).
# Output style: CI-like, clinical, phase-based.
#
# Networking: always uses 127.0.0.1 for stability in WSL setups.

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANAGER_DIR="$ROOT_DIR/apps/manager"

PORT="${TCM_PORT:-8005}"
HTTP_BASE="${TCM_HTTP_BASE:-http://127.0.0.1:${PORT}}"
WS_URL="${TCM_WS_URL:-ws://127.0.0.1:${PORT}/ws}"

# ---------- styling ----------
if [[ -t 1 ]]; then
  RED=$'\033[31m'; GRN=$'\033[32m'; YLW=$'\033[33m'; BLU=$'\033[34m'; BLD=$'\033[1m'; RST=$'\033[0m'
else
  RED=""; GRN=""; YLW=""; BLU=""; BLD=""; RST=""
fi

ok()    { printf "%s\n" "${GRN}PASSED${RST} $*"; }
fail()  { printf "%s\n" "${RED}FAILED${RST} $*"; }
skip()  { printf "%s\n" "${YLW}SKIPPED${RST} $*"; }
info()  { printf "%s\n" "${BLU}INFO${RST}   $*"; }
hdr()   { printf "\n%s\n" "${BLD}== $* ==${RST}"; }

run_cmd() {
  local name="$1"; shift
  info "RUN $name"
  if "$@"; then
    ok "$name"
    return 0
  fi
  fail "$name"
  return 1
}

have() { command -v "$1" >/dev/null 2>&1; }

manager_up() {
  have curl || return 1
  curl -fsS "${HTTP_BASE}/health" >/dev/null 2>&1
}

find_pid_by_port() {
  local port="$1"
  local pid=""
  if have ss; then
    # Example: users:(("python",pid=1234,fd=3))
    pid="$(ss -ltnp 2>/dev/null | awk -v p=":${port}" '$4 ~ p {print $0}' | sed -n 's/.*pid=\([0-9]\+\).*/\1/p' | head -n 1)"
  fi
  if [[ -z "$pid" ]] && have lsof; then
    pid="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
  fi
  [[ -n "$pid" ]] && echo "$pid"
}

inventory() {
  hdr "Inventory"
  info "Root: ${ROOT_DIR}"
  info "Manager dir: ${MANAGER_DIR}"

  local n_pytests n_devtools
  n_pytests="$(find "${MANAGER_DIR}/tests" -type f -name 'test_*.py' 2>/dev/null | wc -l | tr -d ' ')"
  n_devtools="$(find "${MANAGER_DIR}/devtools" -type f -name 'qa_*.py' 2>/dev/null | wc -l | tr -d ' ')"
  info "pytest test files: ${n_pytests}"
  info "qa devtools scripts: ${n_devtools}"

  info "Key locations:"
  printf "  - %s\n" "apps/manager/tests/ (pytest)"
  printf "  - %s\n" "apps/manager/devtools/ (load/chaos tools)"
  printf "  - %s\n" "scripts/sync_sdk.py (vendored SDK check)"
}

# ---------- phases ----------
phase_1_unit() {
  hdr "PHASE 1 — Unit & Functional (pytest)"
  (cd "$MANAGER_DIR" && run_cmd "pytest" python -m pytest -q)
}

phase_2_resilience() {
  hdr "PHASE 2 — Resilience & Error Mapping (targeted)"
  (cd "$MANAGER_DIR" && run_cmd "classification unit tests" python -m pytest -q tests/test_error_classification_unit.py)
}

phase_3_load() {
  hdr "PHASE 3 — High-Load & Performance (1000+ WS clients)"

  if ! manager_up; then
    skip "Manager not detected at ${HTTP_BASE} (start it, then rerun)."
    info "Hint: run the manager and ensure /health is reachable on 127.0.0.1:${PORT}"
    return 0
  fi

  # This test does not require a real Triton backend if max_request_payload_mb is enabled,
  # because the 413 admission control triggers before contacting Triton.
  local clients="${TCM_CLIENTS:-1000}"
  local reqs="${TCM_REQUESTS_PER_CLIENT:-1}"
  # Default to 0 to match repo config (admission control disabled unless explicitly enabled).
  # To validate 413 behavior, set TCM_MAX_REQUEST_PAYLOAD_MB>0 when starting the manager AND running this suite.
  local max_mb="${TCM_MAX_REQUEST_PAYLOAD_MB:-0}"
  local over_ratio="${TCM_OVERSIZE_RATIO:-0.30}"
  local allow_transient="${TCM_ALLOW_TRANSIENT:-0}"
  local timeout_s="${TCM_TIMEOUT_S:-60}"

  local transient_flag=()
  if [[ "${allow_transient}" == "1" ]]; then
    transient_flag+=(--allow-transient)
  fi

  run_cmd "load tester (${clients} clients)" \
    python "${MANAGER_DIR}/devtools/qa_load_tester_ws.py" \
      --ws-url "${WS_URL}" \
      --clients "${clients}" \
      --requests-per-client "${reqs}" \
      --timeout-s "${timeout_s}" \
      --max-request-payload-mb "${max_mb}" \
      --oversize-ratio "${over_ratio}" \
      --vm-ip "${TCM_VM_IP:-127.0.0.1}" \
      --container-id "${TCM_CONTAINER_ID:-cid-qa}" \
      --model-name "${TCM_MODEL_NAME:-model-qa}" \
      "${transient_flag[@]}"
}

phase_4_chaos() {
  hdr "PHASE 4 — Chaos & SRE"

  if ! manager_up; then
    skip "Manager not detected at ${HTTP_BASE}."
    return 0
  fi

  run_cmd "Flapping Backend (/ready storm)" \
    python "${MANAGER_DIR}/devtools/qa_chaos_flapping_backend.py" \
      --http-base "${HTTP_BASE}" \
      --ws-url "${WS_URL}" \
      --seconds "${TCM_CHAOS_SECONDS:-15}" \
      --ready-qps "${TCM_READY_QPS:-200}" \
      --ws-workers "${TCM_WS_WORKERS:-50}" \
      --max-p99-ms "${TCM_READY_P99_MS:-25}"

  # Zombie Killer requires a real gRPC-streaming model/backend. Gate it explicitly.
  if [[ "${TCM_ENABLE_ZOMBIE_KILLER:-0}" != "1" ]]; then
    skip "Zombie Killer disabled (set TCM_ENABLE_ZOMBIE_KILLER=1 + provide vm/container/model)."
  else
    run_cmd "Zombie Killer (WS close cancels gRPC stream)" \
      python "${MANAGER_DIR}/devtools/qa_chaos_zombie_killer.py" \
        --http-base "${HTTP_BASE}" \
        --ws-url "${WS_URL}" \
        --vm-ip "${TCM_VM_IP:-127.0.0.1}" \
        --container-id "${TCM_CONTAINER_ID:-cid-zombie}" \
        --model-name "${TCM_MODEL_NAME:-model-zombie}" \
        --output-name "${TCM_OUTPUT_NAME:-output}"
  fi

  # SIGTERM draining kills the manager. Gate it explicitly.
  if [[ "${TCM_ENABLE_SIGTERM_TEST:-0}" != "1" ]]; then
    skip "SIGTERM draining test disabled (set TCM_ENABLE_SIGTERM_TEST=1)."
    return 0
  fi

  local pid="${TCM_MANAGER_PID:-}"
  if [[ -z "$pid" ]]; then
    pid="$(find_pid_by_port "$PORT" || true)"
  fi

  if [[ -z "$pid" ]]; then
    skip "Could not determine Manager PID on port ${PORT} (set TCM_MANAGER_PID)."
    return 0
  fi

  run_cmd "Shutdown draining (SIGTERM -> SYSTEM_SHUTDOWN NACKs)" \
    python "${MANAGER_DIR}/devtools/qa_shutdown_draining_sigterm.py" \
      --manager-pid "${pid}" \
      --ws-url "${WS_URL}" \
      --clients "${TCM_SHUTDOWN_CLIENTS:-100}"
}

usage() {
  cat <<'EOF'
Usage:
  bash test_suite_master.sh --full
  bash test_suite_master.sh --unit
  bash test_suite_master.sh --stress

Environment defaults (127.0.0.1 stable):
  TCM_PORT=8005
  TCM_HTTP_BASE=http://127.0.0.1:8005
  TCM_WS_URL=ws://127.0.0.1:8005/ws

Stress/Chaos toggles:
  TCM_ENABLE_ZOMBIE_KILLER=1      # requires real gRPC streaming backend/model
  TCM_ENABLE_SIGTERM_TEST=1       # will SIGTERM the running manager process
  TCM_MANAGER_PID=<pid>           # optional; auto-detected by port when possible
EOF
}

mode="${1:---full}"
case "$mode" in
  --full)
    inventory
    phase_1_unit
    phase_2_resilience
    phase_3_load
    phase_4_chaos
    ;;
  --unit)
    inventory
    phase_1_unit
    phase_2_resilience
    ;;
  --stress)
    inventory
    phase_3_load
    phase_4_chaos
    ;;
  -h|--help)
    usage
    exit 0
    ;;
  *)
    usage
    exit 2
    ;;
esac

hdr "Suite complete"
