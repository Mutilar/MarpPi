#!/bin/bash
# setup-wifi-direct.sh
# Configures Raspberry Pi 5 as a Wi-Fi Direct Group Owner (GO)
# and sets up a DHCP server for clients (Steam Deck).

set -e

if [ "$EUID" -ne 0 ]; then
  echo "Please run as root"
  exit
fi

echo "Installing dependencies..."
apt-get update && apt-get install -y dnsmasq psmisc

# Configuration Variables
IFACE="wlan0"
P2P_IFACE="p2p-wlan0-0" # This is the typical virtual interface name
IP_ADDR="192.168.4.1"
DHCP_RANGE="192.168.4.2,192.168.4.10,12h"
CONF_FILE="/etc/wpa_supplicant/wpa_supplicant-p2p.conf"

echo "Creating wpa_supplicant P2P configuration..."
cat > "$CONF_FILE" <<EOF
ctrl_interface=DIR=/var/run/wpa_supplicant GROUP=netdev
update_config=1
country=US
device_name=MARP
p2p_go_intent=15
p2p_go_ht40=1
driver_param=use_p2p_group_interface=1

network={
    ssid="MARP-Robot"
    psk="c74cdffd-63a7-4da7-b935-db49d3fefdfc"
    mode=2
    disabled=2
}
EOF

echo "Stopping conflicting services..."
# On Bookworm, NetworkManager manages wlan0. We might need to stop it or unmanage wlan0.
# For this standalone script, we'll stop it temporarily.
systemctl stop NetworkManager || true
killall wpa_supplicant || true

echo "Starting wpa_supplicant..."
wpa_supplicant -B -i "$IFACE" -c "$CONF_FILE" -D nl80211

echo "Waiting for P2P interface..."
sleep 3

# Force Group Owner mode
echo "Initializing P2P Group..."
wpa_cli -i "$IFACE" p2p_group_add persistent=0

echo "Waiting for virtual interface $P2P_IFACE..."
sleep 3

if ip link show "$P2P_IFACE" > /dev/null 2>&1; then
    echo "Configuring IP address for $P2P_IFACE..."
    ip addr add "$IP_ADDR/24" dev "$P2P_IFACE"
    ip link set "$P2P_IFACE" up
else
    echo "Error: Interface $P2P_IFACE not found. Check wpa_supplicant logs."
    exit 1
fi

echo "Configuring DHCP server (dnsmasq)..."
# Kill existing dnsmasq to avoid conflicts
killall dnsmasq || true

cat > /tmp/dnsmasq-p2p.conf <<EOF
interface=$P2P_IFACE
dhcp-range=$DHCP_RANGE
EOF

dnsmasq -C /tmp/dnsmasq-p2p.conf

echo "Wi-Fi Direct Group Owner started."
echo "IP: $IP_ADDR"
echo "Connect your Steam Deck to the Wi-Fi network named 'MARP-Robot'."
echo "Password: c74cdffd-63a7-4da7-b935-db49d3fefdfc"
echo "The Steam Deck should receive an IP in the 192.168.4.x range."
