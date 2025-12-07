#!/usr/bin/env python3
"""
Service Status Monitor for Raspberry Pi
========================================

Monitors systemd services and power/throttling status.
Shows desktop notifications and optional system tray icon.

Features:
- Desktop notifications on service status changes
- Power throttling detection and warnings  
- System tray icon with status menu (if available)
- Log file for debugging boot issues

Usage:
    python3 service-monitor.py [--tray] [--once] [--log]
    
Options:
    --tray   Show system tray icon (requires GTK)
    --once   Check once and exit (for boot scripts)
    --log    Write status to log file
"""

import subprocess
import time
import sys
import os
import argparse
from datetime import datetime
from pathlib import Path

# Services to monitor
SERVICES = [
    'video-stream.service',
    'stepper-controller.service',
    'softap.service',
]

# Throttle status bits (from vcgencmd get_throttled)
THROTTLE_FLAGS = {
    0: 'Under-voltage detected',
    1: 'Arm frequency capped',
    2: 'Currently throttled',
    3: 'Soft temperature limit active',
    16: 'Under-voltage has occurred',
    17: 'Arm frequency capping has occurred',
    18: 'Throttling has occurred',
    19: 'Soft temperature limit has occurred',
}

LOG_FILE = Path('/tmp/service-monitor.log')

# Optional imports for GUI features
try:
    import gi
    gi.require_version('Notify', '0.7')
    from gi.repository import Notify
    NOTIFY_AVAILABLE = True
    Notify.init('Service Monitor')
except (ImportError, ValueError):
    NOTIFY_AVAILABLE = False

try:
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, GLib
    # Try AyatanaAppIndicator3 first (Raspberry Pi OS / Debian), then fall back to AppIndicator3 (Ubuntu)
    try:
        gi.require_version('AyatanaAppIndicator3', '0.1')
        from gi.repository import AyatanaAppIndicator3 as AppIndicator3
    except ValueError:
        gi.require_version('AppIndicator3', '0.1')
        from gi.repository import AppIndicator3
    TRAY_AVAILABLE = True
except (ImportError, ValueError):
    TRAY_AVAILABLE = False


def log(message, to_file=False):
    """Print and optionally log message"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f"[{timestamp}] {message}"
    print(line)
    if to_file:
        with open(LOG_FILE, 'a') as f:
            f.write(line + '\n')


def get_service_status(service):
    """Get status of a systemd service"""
    try:
        result = subprocess.run(
            ['systemctl', 'is-active', service],
            capture_output=True, text=True, timeout=5
        )
        status = result.stdout.strip()
        return status
    except Exception as e:
        return f'error: {e}'


def get_all_service_status():
    """Get status of all monitored services"""
    statuses = {}
    for service in SERVICES:
        statuses[service] = get_service_status(service)
    return statuses


def get_throttle_status():
    """Check for power throttling issues"""
    try:
        result = subprocess.run(
            ['vcgencmd', 'get_throttled'],
            capture_output=True, text=True, timeout=5
        )
        # Output format: throttled=0x0
        output = result.stdout.strip()
        if '=' in output:
            hex_val = output.split('=')[1]
            value = int(hex_val, 16)
            return value
        return 0
    except Exception:
        return None


def decode_throttle_status(value):
    """Decode throttle bits into human-readable messages"""
    if value is None:
        return ['Could not read throttle status']
    if value == 0:
        return []
    
    issues = []
    for bit, message in THROTTLE_FLAGS.items():
        if value & (1 << bit):
            issues.append(message)
    return issues


def get_power_status():
    """Get power-related information"""
    info = {}
    
    # Throttle status
    throttle = get_throttle_status()
    info['throttle_raw'] = throttle
    info['throttle_issues'] = decode_throttle_status(throttle)
    
    # CPU temperature
    try:
        result = subprocess.run(
            ['vcgencmd', 'measure_temp'],
            capture_output=True, text=True, timeout=5
        )
        # Output: temp=45.0'C
        temp_str = result.stdout.strip().replace("temp=", "").replace("'C", "")
        info['cpu_temp'] = float(temp_str)
    except:
        info['cpu_temp'] = None
    
    # Voltage
    try:
        result = subprocess.run(
            ['vcgencmd', 'measure_volts', 'core'],
            capture_output=True, text=True, timeout=5
        )
        # Output: volt=0.8563V
        volt_str = result.stdout.strip().replace("volt=", "").replace("V", "")
        info['core_voltage'] = float(volt_str)
    except:
        info['core_voltage'] = None
        
    return info


def send_notification(title, message, icon='dialog-information', urgency='normal'):
    """Send desktop notification"""
    if NOTIFY_AVAILABLE:
        try:
            notif = Notify.Notification.new(title, message, icon)
            if urgency == 'critical':
                notif.set_urgency(Notify.Urgency.CRITICAL)
            elif urgency == 'low':
                notif.set_urgency(Notify.Urgency.LOW)
            notif.show()
            return True
        except Exception as e:
            log(f"Notification error: {e}")
    
    # Fallback: try notify-send command
    try:
        urgency_flag = {'low': 'low', 'normal': 'normal', 'critical': 'critical'}.get(urgency, 'normal')
        subprocess.run([
            'notify-send', '-u', urgency_flag, '-i', icon, title, message
        ], timeout=5)
        return True
    except:
        pass
    
    return False


def format_status_message(statuses, power_info):
    """Format status information into a message"""
    lines = []
    
    # Services
    all_ok = True
    for service, status in statuses.items():
        name = service.replace('.service', '')
        if status == 'active':
            lines.append(f"✓ {name}: running")
        else:
            lines.append(f"✗ {name}: {status}")
            all_ok = False
    
    # Power issues
    if power_info['throttle_issues']:
        lines.append("")
        lines.append("⚠ Power Issues:")
        for issue in power_info['throttle_issues']:
            lines.append(f"  • {issue}")
    
    # Temperature
    if power_info['cpu_temp'] is not None:
        temp = power_info['cpu_temp']
        if temp > 80:
            lines.append(f"🌡 CPU: {temp}°C (HIGH!)")
        elif temp > 70:
            lines.append(f"🌡 CPU: {temp}°C (warm)")
    
    return '\n'.join(lines), all_ok


def check_once(log_to_file=False):
    """Check status once and report"""
    log("=" * 50, log_to_file)
    log("Service Monitor - Status Check", log_to_file)
    log("=" * 50, log_to_file)
    
    # Get statuses
    statuses = get_all_service_status()
    power_info = get_power_status()
    
    # Log individual service status
    for service, status in statuses.items():
        log(f"  {service}: {status}", log_to_file)
    
    # Log power info
    if power_info['throttle_issues']:
        log("Power issues detected:", log_to_file)
        for issue in power_info['throttle_issues']:
            log(f"  ⚠ {issue}", log_to_file)
    else:
        log("Power: OK (no throttling)", log_to_file)
    
    if power_info['cpu_temp']:
        log(f"CPU Temperature: {power_info['cpu_temp']}°C", log_to_file)
    
    # Format and show notification
    message, all_ok = format_status_message(statuses, power_info)
    
    if all_ok and not power_info['throttle_issues']:
        send_notification(
            "🤖 Robot Services Ready",
            message,
            icon='dialog-information',
            urgency='low'
        )
    elif power_info['throttle_issues']:
        send_notification(
            "⚠️ Power Issue Detected",
            message,
            icon='dialog-warning',
            urgency='critical'
        )
    else:
        send_notification(
            "⚠️ Service Issue",
            message,
            icon='dialog-warning',
            urgency='normal'
        )
    
    log("=" * 50, log_to_file)
    
    return all_ok and not power_info['throttle_issues']


class TrayIndicator:
    """System tray indicator for service status"""
    
    def __init__(self):
        if not TRAY_AVAILABLE:
            raise RuntimeError("GTK/AppIndicator not available")
        
        self.indicator = AppIndicator3.Indicator.new(
            "service-monitor",
            "network-idle",
            AppIndicator3.IndicatorCategory.SYSTEM_SERVICES
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
        
        self.last_statuses = {}
        self.last_power = {}
        
        # Create menu
        self.menu = Gtk.Menu()
        
        # Service items
        self.service_items = {}
        for service in SERVICES:
            name = service.replace('.service', '')
            item = Gtk.MenuItem(label=f"{name}: checking...")
            item.set_sensitive(False)
            self.menu.append(item)
            self.service_items[service] = item
        
        self.menu.append(Gtk.SeparatorMenuItem())
        
        # Power status item
        self.power_item = Gtk.MenuItem(label="Power: checking...")
        self.power_item.set_sensitive(False)
        self.menu.append(self.power_item)
        
        # Temperature item
        self.temp_item = Gtk.MenuItem(label="Temp: --")
        self.temp_item.set_sensitive(False)
        self.menu.append(self.temp_item)
        
        self.menu.append(Gtk.SeparatorMenuItem())
        
        # Refresh item
        refresh_item = Gtk.MenuItem(label="Refresh Now")
        refresh_item.connect('activate', self.on_refresh)
        self.menu.append(refresh_item)
        
        # Quit item
        quit_item = Gtk.MenuItem(label="Quit Monitor")
        quit_item.connect('activate', self.on_quit)
        self.menu.append(quit_item)
        
        self.menu.show_all()
        self.indicator.set_menu(self.menu)
        
        # Start update timer
        GLib.timeout_add_seconds(10, self.update_status)
        self.update_status()
    
    def update_status(self):
        """Update status in tray"""
        statuses = get_all_service_status()
        power_info = get_power_status()
        
        # Check for changes and notify
        if self.last_statuses:
            for service, status in statuses.items():
                old_status = self.last_statuses.get(service)
                if old_status and old_status != status:
                    name = service.replace('.service', '')
                    if status == 'active':
                        send_notification(f"✓ {name}", "Service started", urgency='low')
                    else:
                        send_notification(f"✗ {name}", f"Service {status}", urgency='normal')
        
        self.last_statuses = statuses
        self.last_power = power_info
        
        # Update menu items
        all_ok = True
        for service, status in statuses.items():
            name = service.replace('.service', '')
            item = self.service_items[service]
            if status == 'active':
                item.set_label(f"✓ {name}: running")
            else:
                item.set_label(f"✗ {name}: {status}")
                all_ok = False
        
        # Update power status
        if power_info['throttle_issues']:
            self.power_item.set_label(f"⚠ Power: {len(power_info['throttle_issues'])} issue(s)")
            all_ok = False
        else:
            self.power_item.set_label("✓ Power: OK")
        
        # Update temperature
        if power_info['cpu_temp']:
            temp = power_info['cpu_temp']
            if temp > 80:
                self.temp_item.set_label(f"🌡 Temp: {temp}°C (HIGH!)")
                all_ok = False
            elif temp > 70:
                self.temp_item.set_label(f"🌡 Temp: {temp}°C (warm)")
            else:
                self.temp_item.set_label(f"🌡 Temp: {temp}°C")
        
        # Update icon
        if all_ok:
            self.indicator.set_icon("network-idle")
        else:
            self.indicator.set_icon("network-error")
        
        return True  # Continue timer
    
    def on_refresh(self, widget):
        self.update_status()
    
    def on_quit(self, widget):
        Gtk.main_quit()
    
    def run(self):
        Gtk.main()


def main():
    parser = argparse.ArgumentParser(description='Service Status Monitor')
    parser.add_argument('--tray', action='store_true', 
                        help='Show system tray icon')
    parser.add_argument('--once', action='store_true',
                        help='Check once and exit')
    parser.add_argument('--log', action='store_true',
                        help='Log to file')
    args = parser.parse_args()
    
    if args.once:
        # Single check mode
        success = check_once(log_to_file=args.log)
        sys.exit(0 if success else 1)
    
    if args.tray:
        if not TRAY_AVAILABLE:
            print("Error: System tray requires GTK and AppIndicator3")
            print("Install with: sudo apt install gir1.2-appindicator3-0.1 python3-gi")
            sys.exit(1)
        
        log("Starting system tray indicator...")
        indicator = TrayIndicator()
        indicator.run()
    else:
        # Continuous monitoring without tray
        log("Starting continuous monitoring (Ctrl+C to stop)...")
        try:
            while True:
                check_once(log_to_file=args.log)
                time.sleep(30)
        except KeyboardInterrupt:
            log("Stopped.")


if __name__ == '__main__':
    main()
