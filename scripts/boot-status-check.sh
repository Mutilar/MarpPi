#!/bin/bash
# boot-status-check.sh
# Run at boot to check power/throttle status and log issues
# This runs early before other services to detect power problems

SCRIPT_DIR="$(dirname "$0")"
LOG_FILE="/tmp/boot-status.log"

echo "=== Boot Status Check $(date) ===" > "$LOG_FILE"

# Check for throttling
THROTTLE=$(vcgencmd get_throttled 2>/dev/null | cut -d= -f2)
if [ -n "$THROTTLE" ]; then
    echo "Throttle status: $THROTTLE" >> "$LOG_FILE"
    
    # Decode throttle bits
    VAL=$((THROTTLE))
    if [ $VAL -ne 0 ]; then
        echo "⚠ POWER ISSUES DETECTED:" >> "$LOG_FILE"
        
        [ $((VAL & 0x1)) -ne 0 ] && echo "  - Under-voltage detected NOW" >> "$LOG_FILE"
        [ $((VAL & 0x2)) -ne 0 ] && echo "  - ARM frequency capped NOW" >> "$LOG_FILE"
        [ $((VAL & 0x4)) -ne 0 ] && echo "  - Currently throttled" >> "$LOG_FILE"
        [ $((VAL & 0x8)) -ne 0 ] && echo "  - Soft temp limit active" >> "$LOG_FILE"
        [ $((VAL & 0x10000)) -ne 0 ] && echo "  - Under-voltage has occurred since boot" >> "$LOG_FILE"
        [ $((VAL & 0x20000)) -ne 0 ] && echo "  - ARM freq capping has occurred" >> "$LOG_FILE"
        [ $((VAL & 0x40000)) -ne 0 ] && echo "  - Throttling has occurred" >> "$LOG_FILE"
        [ $((VAL & 0x80000)) -ne 0 ] && echo "  - Soft temp limit has occurred" >> "$LOG_FILE"
    else
        echo "✓ No power issues" >> "$LOG_FILE"
    fi
else
    echo "Could not read throttle status" >> "$LOG_FILE"
fi

# Check temperature
TEMP=$(vcgencmd measure_temp 2>/dev/null | cut -d= -f2 | cut -d\' -f1)
if [ -n "$TEMP" ]; then
    echo "CPU Temperature: ${TEMP}°C" >> "$LOG_FILE"
fi

# Check voltage
VOLT=$(vcgencmd measure_volts core 2>/dev/null | cut -d= -f2 | tr -d 'V')
if [ -n "$VOLT" ]; then
    echo "Core Voltage: ${VOLT}V" >> "$LOG_FILE"
fi

# Wait a moment then check service status
sleep 5

echo "" >> "$LOG_FILE"
echo "=== Service Status ===" >> "$LOG_FILE"
for SERVICE in video-stream stepper-controller softap; do
    STATUS=$(systemctl is-active ${SERVICE}.service 2>/dev/null)
    echo "  ${SERVICE}: ${STATUS:-unknown}" >> "$LOG_FILE"
done

# If there were power issues and we're in a graphical session, notify
if [ $VAL -ne 0 ] && [ -n "$DISPLAY" ]; then
    notify-send -u critical "⚠️ Power Issue" \
        "Throttling detected (0x$(printf '%x' $VAL)). Check power supply." \
        2>/dev/null || true
fi

echo "" >> "$LOG_FILE"
echo "Boot check complete." >> "$LOG_FILE"

# Also output to journal
cat "$LOG_FILE" | logger -t boot-status

exit 0
