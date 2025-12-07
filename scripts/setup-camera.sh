#!/bin/bash
# setup-camera.sh
# Configures the Raspberry Pi to use the IMX708 camera sensor.

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit
fi

CONFIG_FILE=""
if [ -f "/boot/firmware/config.txt" ]; then
    CONFIG_FILE="/boot/firmware/config.txt"
elif [ -f "/boot/config.txt" ]; then
    CONFIG_FILE="/boot/config.txt"
else
    echo "Error: Could not find config.txt in /boot/firmware/ or /boot/"
    exit 1
fi

echo "Found config file at $CONFIG_FILE"

# Backup
cp "$CONFIG_FILE" "$CONFIG_FILE.bak"
echo "Backed up config to $CONFIG_FILE.bak"

# Disable camera_auto_detect if present
if grep -q "camera_auto_detect=1" "$CONFIG_FILE"; then
    sed -i 's/camera_auto_detect=1/camera_auto_detect=0/' "$CONFIG_FILE"
    echo "Disabled camera_auto_detect"
fi

# Add dtoverlay=imx708 if not present
if ! grep -q "dtoverlay=imx708" "$CONFIG_FILE"; then
    # Add it under [all] if it exists, otherwise just append
    if grep -q "\[all\]" "$CONFIG_FILE"; then
        # Append after [all]
        sed -i '/\[all\]/a dtoverlay=imx708' "$CONFIG_FILE"
    else
        echo "dtoverlay=imx708" >> "$CONFIG_FILE"
    fi
    echo "Added dtoverlay=imx708"
else
    echo "dtoverlay=imx708 already present"
fi

echo "Camera configuration updated. Please reboot for changes to take effect."
