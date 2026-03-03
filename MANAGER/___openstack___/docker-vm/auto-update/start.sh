#!/bin/bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Setup script for auto-update service

echo "Setting up auto-update service..."

# Create symlink to systemd
sudo ln -sf /home/ubuntu/auto-update/auto-update.service /etc/systemd/system/auto-update.service

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
