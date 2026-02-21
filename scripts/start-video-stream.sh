#!/bin/bash
# start-video-stream.sh
# Streams MJPEG video from the Arducam IMX708 Pi Camera via rpicam-vid.
#
# Usage:
#   ./start-video-stream.sh [--resolution PRESET] [--port PORT] [--quality Q]
#
# Resolution presets:
#   low    = 640x480  @ 30 fps
#   medium = 1280x720 @ 24 fps
#   high   = 1280x800 @ 24 fps  (default)
#   full   = 1920x1080 @ 15 fps

set -euo pipefail

PORT=5600
RESOLUTION="high"
QUALITY=70

# ── Parse arguments ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case $1 in
        --resolution) RESOLUTION="$2"; shift 2 ;;
        --port)       PORT="$2";       shift 2 ;;
        --quality)    QUALITY="$2";    shift 2 ;;
        *)            shift ;;
    esac
done

# ── Resolve preset ───────────────────────────────────────────────────────────
case "$RESOLUTION" in
    low)    WIDTH=640;  HEIGHT=480;  FPS=30 ;;
    medium) WIDTH=1280; HEIGHT=720;  FPS=24 ;;
    high)   WIDTH=1280; HEIGHT=800;  FPS=24 ;;
    full)   WIDTH=1920; HEIGHT=1080; FPS=15 ;;
    *)
        echo "Unknown resolution preset: $RESOLUTION"
        echo "Valid presets: low, medium, high, full"
        exit 1
        ;;
esac

# ── Detect camera command ────────────────────────────────────────────────────
CAM_CMD=""
for cmd in rpicam-vid libcamera-vid; do
    if command -v "$cmd" &>/dev/null; then
        CAM_CMD="$cmd"
        break
    fi
done

if [[ -z "$CAM_CMD" ]]; then
    echo "Error: neither rpicam-vid nor libcamera-vid found."
    exit 1
fi

# ── Cleanup ──────────────────────────────────────────────────────────────────
cleanup() {
    echo ""
    echo "Stopping video stream..."
    pkill -x rpicam-vid  2>/dev/null || true
    pkill -x libcamera-vid 2>/dev/null || true
    echo "Stopped."
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# Kill any existing camera processes
pkill -x rpicam-vid    2>/dev/null || true
pkill -x libcamera-vid 2>/dev/null || true
sleep 1

# ── Start stream ─────────────────────────────────────────────────────────────
echo "=============================================="
echo "  Arducam IMX708 — MJPEG Stream"
echo "=============================================="
echo "  Camera:     $CAM_CMD"
echo "  Resolution: ${WIDTH}x${HEIGHT} @ ${FPS} fps"
echo "  Quality:    $QUALITY"
echo "  Stream:     http://0.0.0.0:${PORT}/stream.mjpg"
echo "=============================================="

exec $CAM_CMD \
    --width  "$WIDTH" \
    --height "$HEIGHT" \
    --framerate "$FPS" \
    --codec mjpeg \
    --quality "$QUALITY" \
    --listen \
    --output "tcp://0.0.0.0:${PORT}" \
    --timeout 0 \
    --nopreview
