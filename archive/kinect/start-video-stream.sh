#!/bin/bash
# start-video-stream.sh
# Unified video streaming with hot-swappable sources.
#
# This script starts the Video Multiplexer which provides:
#   - Single persistent MJPEG stream on port 5600
#   - Web viewer at http://<ip>:5600/
#   - Hot-swap between: kinect_rgb, kinect_ir, kinect_depth, picam
#   - TCP control on port 5603

SCRIPT_DIR="$(dirname "$0")"
PORT=5600
PYTHON_PID=""

# Cleanup function
cleanup() {
    echo ""
    echo "Stopping video stream..."
    
    # Kill the Python process we started
    if [[ -n "$PYTHON_PID" ]] && kill -0 "$PYTHON_PID" 2>/dev/null; then
        kill -TERM "$PYTHON_PID" 2>/dev/null
        # Wait briefly for graceful shutdown
        for i in {1..10}; do
            if ! kill -0 "$PYTHON_PID" 2>/dev/null; then
                break
            fi
            sleep 0.2
        done
        # Force kill if still running
        if kill -0 "$PYTHON_PID" 2>/dev/null; then
            kill -9 "$PYTHON_PID" 2>/dev/null
        fi
    fi
    
    # Clean up any remaining child processes
    pkill -P $$ 2>/dev/null
    pkill -f "video_multiplexer/__main__.py" 2>/dev/null
    pkill -f kinect_stream.py 2>/dev/null
    pkill -x rpicam-vid 2>/dev/null
    pkill -x libcamera-vid 2>/dev/null
    
    echo "Stopped."
    exit 0
}
trap cleanup SIGINT SIGTERM EXIT

# Clean up any existing processes (but not via systemctl to avoid deadlock when run as service)
echo "Cleaning up existing processes..."
pkill -f "video_multiplexer/__main__.py" 2>/dev/null
pkill -f kinect_stream.py 2>/dev/null
pkill -x rpicam-vid 2>/dev/null
pkill -x libcamera-vid 2>/dev/null
pkill -x ffmpeg 2>/dev/null
sleep 1

# Parse arguments
DEBUG=""
SOURCE="kinect_rgb"

while [[ $# -gt 0 ]]; do
    case $1 in
        --debug)
            DEBUG="--debug"
            shift
            ;;
        --source)
            SOURCE="$2"
            shift 2
            ;;
        *)
            shift
            ;;
    esac
done

echo "==============================================" 
echo "Starting Video Multiplexer"
echo "==============================================" 
echo "  Web Viewer: http://localhost:$PORT/"
echo "  Stream:     http://localhost:$PORT/stream.mjpg"
echo "  Control:    TCP port 5603"
echo "  Source:     $SOURCE"
echo "==============================================" 

# Start the unified video multiplexer (no exec, so trap can work)
# Run as module from the scripts directory so relative imports work
cd "$SCRIPT_DIR"
python3 -m video_multiplexer --main-port $PORT --main-source "$SOURCE" $DEBUG &
PYTHON_PID=$!

# Wait for Python process and forward its exit code
wait $PYTHON_PID
exit $?