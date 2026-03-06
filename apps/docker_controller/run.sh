#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

DOCKER_INSTALL="${SCRIPT_DIR}/docker_installation.sh"
START_CONTAINER="${SCRIPT_DIR}/start_container.sh"
SETUP_ENV="${SCRIPT_DIR}/setup_environment.sh"

echo "==> Starting execution from: ${SCRIPT_DIR}"

# 1) Install Docker if missing
if ! command -v docker >/dev/null 2>&1; then
  echo "==> Docker not found. Running docker_installation.sh..."
  bash "$DOCKER_INSTALL"
else
  echo "==> Docker is installed. Skipping docker_installation.sh."
fi

# Ensure Docker daemon is reachable (best effort)
if command -v docker >/dev/null 2>&1; then
  if ! sudo docker info >/dev/null 2>&1; then
    echo "==> Docker installed but daemon not reachable. Trying to start docker..."
    sudo systemctl start docker || true
  fi
fi

# 2) Start registry container if missing
if command -v docker >/dev/null 2>&1; then
  if sudo docker ps -a --format '{{.Names}}' | grep -qx 'registry'; then
    echo "==> Container 'registry' already exists. Skipping start_container.sh."
  else
    echo "==> Container 'registry' not found. Running start_container.sh..."
    bash "$START_CONTAINER"
  fi
else
  echo "==> Docker still not available; cannot start container. Skipping start_container.sh."
fi

# 3) Always run setup_environment.sh last
echo "==> Running setup_environment.sh (always last)..."
bash "$SETUP_ENV"

echo "==> Done."