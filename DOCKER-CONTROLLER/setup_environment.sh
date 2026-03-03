#!/bin/bash
set -e

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

# python3-venv is not pre-installed on most Ubuntu cloud images
sudo apt install -y python3 python3-venv

python3 -m venv "$SCRIPT_DIR/venv"
source "$SCRIPT_DIR/venv/bin/activate"
pip install -r "$SCRIPT_DIR/requirements.txt"

echo "Running pre-flight tests..."
python3 "$SCRIPT_DIR/test/gitlab.py"       || { echo "==> FAIL: gitlab test failed. Aborting.";        exit 1; }
python3 "$SCRIPT_DIR/test/docker_images.py" || { echo "==> FAIL: docker_images test failed. Aborting."; exit 1; }
python3 "$SCRIPT_DIR/test/local_registry.py" || { echo "==> FAIL: local_registry test failed. Aborting."; exit 1; }
echo "All pre-flight tests passed."

echo "Setting up auto-update service..."

# Write token to a root-owned env file that systemd will load
sudo mkdir -p /etc/auto-update
sudo tee /etc/auto-update/env > /dev/null <<EOF
GITLAB_TOKEN=${GITLAB_TOKEN:?GITLAB_TOKEN environment variable must be set}
GITLAB_TOKEN_NAME=${GITLAB_TOKEN_NAME:-docker-vm-pull-token}
EOF
sudo chmod 600 /etc/auto-update/env

# Generate service file with paths resolved to the current deploy location
sudo tee /etc/systemd/system/auto-update.service > /dev/null <<EOF
[Unit]
Description=GitLab Registry Auto-Update Service
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=$(whoami)
WorkingDirectory=${SCRIPT_DIR}
EnvironmentFile=/etc/auto-update/env
ExecStart=${SCRIPT_DIR}/venv/bin/python3 -u ${SCRIPT_DIR}/main.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# Reload systemd
sudo systemctl daemon-reload

# Enable service
sudo systemctl enable auto-update.service

# Start service
sudo systemctl start auto-update.service

# Show status
sudo systemctl status auto-update.service

echo ""
echo "Service setup complete!"
echo ""
echo "Useful commands:"
echo "  sudo systemctl status auto-update.service    # Check status"
echo "  sudo systemctl stop auto-update.service      # Stop service"
echo "  sudo systemctl start auto-update.service     # Start service"
echo "  sudo systemctl restart auto-update.service   # Restart service"
echo "  sudo journalctl -u auto-update.service -f    # View logs"