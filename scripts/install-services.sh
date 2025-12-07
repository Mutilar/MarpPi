#!/bin/bash
# Installs systemd services with correct paths
# Also sets up desktop autostart for service monitor

set -euo pipefail

if [ "$EUID" -ne 0 ]; then
  echo "Error: Please run as root" >&2
  exit 1
fi

# Get the directory where this script is located (scripts/)
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
# Get the project root (pi/)
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Project Directory: $PROJECT_DIR"

# Service files source
SERVICE_DIR="$PROJECT_DIR/systemd"

# Destination
SYSTEMD_DIR="/etc/systemd/system"

# Verify source directory exists
if [ ! -d "$SERVICE_DIR" ]; then
    echo "Error: Service directory not found: $SERVICE_DIR" >&2
    exit 1
fi

# Make scripts executable
chmod +x "$SCRIPT_DIR"/*.sh 2>/dev/null || true
chmod +x "$SCRIPT_DIR"/*.py 2>/dev/null || true

# Install required Python packages for notifications
echo "Checking Python dependencies..."
apt-get install -y python3-gi gir1.2-notify-0.7 2>/dev/null || \
    echo "Warning: Could not install notification dependencies"

# Optional: For system tray support
apt-get install -y gir1.2-appindicator3-0.1 2>/dev/null || \
    echo "Note: AppIndicator not installed (tray icon won't work)"

# List of services
SERVICES=("softap.service" "stepper-controller.service" "video-stream.service")

for SERVICE in "${SERVICES[@]}"; do
    SOURCE_FILE="$SERVICE_DIR/$SERVICE"
    
    if [ ! -f "$SOURCE_FILE" ]; then
        echo "Warning: Service file not found, skipping: $SOURCE_FILE" >&2
        continue
    fi
    
    echo "Installing $SERVICE..."
    
    # Read file, replace WORKING_DIR with actual path, write to /etc/systemd/system
    sed "s|WORKING_DIR|$PROJECT_DIR|g" "$SOURCE_FILE" > "$SYSTEMD_DIR/$SERVICE"
    
    # Enable service
    systemctl enable "$SERVICE"
    echo "$SERVICE enabled."
done

# Reload systemd once after all services are installed
systemctl daemon-reload

# Set up desktop autostart for service monitor (runs as user)
echo ""
echo "Setting up desktop autostart for service monitor..."
AUTOSTART_DIR="/home/marp/.config/autostart"
mkdir -p "$AUTOSTART_DIR"

# Copy and fix paths in desktop file
DESKTOP_FILE="$SCRIPT_DIR/service-monitor.desktop"
if [ -f "$DESKTOP_FILE" ]; then
    # Update the path in the desktop file
    sed "s|/home/marp/Marp|$PROJECT_DIR|g" "$DESKTOP_FILE" > "$AUTOSTART_DIR/service-monitor.desktop"
    chown marp:marp "$AUTOSTART_DIR/service-monitor.desktop"
    chmod 644 "$AUTOSTART_DIR/service-monitor.desktop"
    echo "Desktop autostart installed."
else
    echo "Warning: Desktop file not found: $DESKTOP_FILE"
fi

echo ""
echo "=============================================="
echo "Installation Complete!"
echo "=============================================="
echo ""
echo "Installed services:"
for SERVICE in "${SERVICES[@]}"; do
    echo "  • ${SERVICE%.service}"
done
echo ""
echo "Desktop monitor: Will start automatically on login"
echo ""
echo "All services will start on next boot."
echo "To start immediately, run:"
echo "  sudo systemctl start softap stepper-controller video-stream"
echo ""
echo "To check status:"
echo "  python3 $SCRIPT_DIR/service-monitor.py --once"
echo ""
echo "To view boot log:"
echo "  cat /tmp/boot-status.log"
