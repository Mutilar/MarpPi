#!/bin/bash
# setup-softap.sh
# Configures Raspberry Pi 5 as a SoftAP (Access Point) using NetworkManager.
# Unlike the Wi-Fi Direct script, this uses the standard NetworkManager service,
# which helps preserve other network functionality (like Ethernet connectivity).

set -e

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit
fi

# Configuration Variables
SSID="MARP"
PASSWORD="68845277"
PHY_IFACE="wlan0"
IFACE="uap0"
CON_NAME="MARP"

echo "Restoring NetworkManager if needed..."
# The wifi-direct script stops these, so we ensure they are back
# Ensure no rogue wpa_supplicant from manual scripts is running
killall wpa_supplicant 2>/dev/null || true

# Stop system-wide dnsmasq to prevent conflicts with NetworkManager's internal dnsmasq
echo "Stopping system dnsmasq..."
systemctl stop dnsmasq 2>/dev/null || true
killall dnsmasq 2>/dev/null || true

systemctl unmask NetworkManager 2>/dev/null || true
systemctl start NetworkManager || true
# Wait for NM to be ready
echo "Waiting for NetworkManager..."
nm-online -q -t 15 || echo "NetworkManager taking a while..."

# Create virtual interface for AP mode (allows simultaneous STA on wlan0)
# We must assign a distinct MAC address to the virtual interface
if ! ip link show "$IFACE" >/dev/null 2>&1; then
    echo "Creating virtual interface $IFACE..."
    # Get wlan0 MAC
    PHY_MAC=$(cat /sys/class/net/$PHY_IFACE/address)
    # Create a new MAC by flipping the locally administered bit (2nd least significant bit of 1st byte)
    # Or just changing the first byte slightly. Let's just change the first octet to '02' (locally administered)
    # Actually, a safer bet is to take the real MAC and modify it slightly.
    # Let's use a fixed prefix for the robot AP to avoid conflicts.
    # But we need it to be valid.
    # Let's just let 'iw' create it, then modify it.
    iw dev "$PHY_IFACE" interface add "$IFACE" type __ap
    
    # Generate a random MAC or modify the existing one
    # Simple approach: set a specific MAC if possible, or trust iw's auto-assignment if it works.
    # The previous output showed 8a:... vs 88:... which IS different.
    # So MAC might not be the issue.
    
    ip link set "$IFACE" up
    
    echo "Waiting for $IFACE to initialize..."
    sleep 3
fi

echo "Configuring SoftAP..."

# Remove old connection if exists
if nmcli connection show "$CON_NAME" >/dev/null 2>&1; then
    echo "Removing existing connection profile..."
    nmcli connection delete "$CON_NAME"
fi

# Remove potential leftover from other scripts or manual setup
if nmcli connection show "MARP-Hotspot" >/dev/null 2>&1; then
    echo "Removing leftover MARP-Hotspot profile..."
    nmcli connection delete "MARP-Hotspot"
fi

# Prevent other connections from auto-grabbing the new interface
echo "Disconnecting any existing connections on $IFACE..."
nmcli device disconnect "$IFACE" 2>/dev/null || true

echo "Creating new Hotspot profile..."
# Create the connection
nmcli con add type wifi ifname "$IFACE" con-name "$CON_NAME" autoconnect yes ssid "$SSID"

# Configure as Access Point
nmcli con modify "$CON_NAME" 802-11-wireless.mode ap
# Removing explicit band setting to allow auto-selection/coexistence with STA channel
# nmcli con modify "$CON_NAME" 802-11-wireless.band bg
nmcli con modify "$CON_NAME" wifi-sec.key-mgmt wpa-psk
nmcli con modify "$CON_NAME" wifi-sec.psk "$PASSWORD"
# Ensure password is stored in the connection file (system-wide)
nmcli con modify "$CON_NAME" wifi-sec.psk-flags 0
# Force WPA2 (RSN) and CCMP for better compatibility
nmcli con modify "$CON_NAME" wifi-sec.proto rsn
nmcli con modify "$CON_NAME" wifi-sec.group ccmp
nmcli con modify "$CON_NAME" wifi-sec.pairwise ccmp

# Set IP settings
# 'shared' method provides DHCP and NAT (internet sharing from eth0)
# We set a static IP for the AP itself to be consistent with the robot setup
nmcli con modify "$CON_NAME" ipv4.method shared
nmcli con modify "$CON_NAME" ipv4.addresses 192.168.4.1/24
# Prevent this connection from becoming the default gateway for the Pi
nmcli con modify "$CON_NAME" ipv4.never-default yes

echo "Starting Hotspot..."
nmcli con up "$CON_NAME"

echo "----------------------------------------"
echo "SoftAP is running."
echo "SSID: $SSID"
echo "Pass: $PASSWORD"
echo "IP:   192.168.4.1"
echo "----------------------------------------"
