#!/bin/bash
set -euo pipefail

REGISTRY_BIND_ADDRESS="${REGISTRY_BIND_ADDRESS:-127.0.0.1}"
REGISTRY_PORT="${REGISTRY_PORT:-5000}"
REGISTRY_DATA_DIR="${REGISTRY_DATA_DIR:-/opt/registry/data}"

if [[ "${REGISTRY_BIND_ADDRESS}" == "0.0.0.0" ]]; then
  echo "==> WARNING: Binding the registry to 0.0.0.0 exposes it on all interfaces."
  echo "==>          Prefer 127.0.0.1 unless you are fronting it with firewall/TLS."
fi

sudo mkdir -p "${REGISTRY_DATA_DIR}"
sudo chown root:root "${REGISTRY_DATA_DIR}"
sudo chmod 700 "${REGISTRY_DATA_DIR}"

sudo docker run -d \
  --restart=always \
  --name registry \
  -p "${REGISTRY_BIND_ADDRESS}:${REGISTRY_PORT}:5000" \
  -v "${REGISTRY_DATA_DIR}:/var/lib/registry" \
  registry:2