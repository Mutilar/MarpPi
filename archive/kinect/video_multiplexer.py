#!/usr/bin/env python3
"""
Unified Video Multiplexer for Pi + Kinect
==========================================

Single persistent MJPEG stream on port 5600 that can hot-swap between:
  - kinect_rgb:   Kinect RGB camera (640x480 native, scalable)
  - kinect_ir:    Kinect IR camera (640x480 native, scalable)
  - kinect_depth: Kinect depth colorized (640x480 native, scalable)
  - picam:        Raspberry Pi Camera (configurable resolution)

Control server on port 5603 accepts commands to switch sources and settings.
Web viewer available at http://<ip>:5600/

Usage:
    python3 video_multiplexer.py [--debug] [--quality 70] [--scale 1.0]
    
Control Commands (send via TCP to port 5603):
    Sources:    kinect_rgb, kinect_ir, kinect_depth, picam
    Quality:    quality <1-100>      (JPEG compression, default 70)
    Scale:      scale <0.25-2.0>     (output scaling factor, default 1.0)
    Pi Res:     picam_res <preset>   (low/medium/high/full)
    Status:     status, help

Resolution Reference:
    Kinect (all modes):  640x480 native (fixed by sync API)
    Pi Camera presets:
        low:    640x480 @ 30fps
        medium: 1280x720 @ 24fps  
        high:   1280x800 @ 24fps (default)
        full:   1920x1080 @ 15fps
"""

import sys
import os
import time
import threading
import subprocess
import signal
import argparse
import io
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import socket

# Add libfreenect python wrapper to path
sys.path.append(os.path.abspath(os.path.join(
    os.path.dirname(__file__), '../libfreenect/build/wrappers/python/python3')))

# Optional imports - gracefully handle missing dependencies
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    print("Warning: OpenCV not available. Install with: pip install opencv-python")
    CV2_AVAILABLE = False

try:
    import freenect
    FREENECT_AVAILABLE = True
except ImportError:
    print("Warning: freenect not available. Kinect sources will be disabled.")
    FREENECT_AVAILABLE = False

# Runtime Kinect availability (may be False even if freenect imported)
KINECT_AVAILABLE = FREENECT_AVAILABLE
KINECT_SOURCES = ['kinect_rgb', 'kinect_ir', 'kinect_depth']

# =============================================================================
# Configuration
# =============================================================================

STREAM_PORT = 5600
CONTROL_PORT = 5603

# Available video sources
ALL_SOURCES = ['kinect_rgb', 'kinect_ir', 'kinect_depth', 'picam']
DEFAULT_SOURCE = 'picam' if not KINECT_AVAILABLE else 'kinect_rgb'

# SOURCES will be dynamically set based on hardware availability
def get_available_sources():
    """Return list of currently available sources"""
    if KINECT_AVAILABLE:
        return ALL_SOURCES[:]
    else:
        return ['picam']

SOURCES = get_available_sources()

# Stream settings
JPEG_QUALITY = 70          # 1-100, higher = better quality, more bandwidth
TARGET_FPS = 15
FRAME_INTERVAL = 1.0 / TARGET_FPS

# Kinect native resolution (fixed by sync API - RESOLUTION_MEDIUM)
KINECT_WIDTH = 640
KINECT_HEIGHT = 480

# Pi Camera resolution presets
PICAM_PRESETS = {
    'low':    {'width': 640,  'height': 480,  'fps': 30},
    'medium': {'width': 1280, 'height': 720,  'fps': 24},
    'high':   {'width': 1280, 'height': 800,  'fps': 24},
    'full':   {'width': 1920, 'height': 1080, 'fps': 15},
}
DEFAULT_PICAM_PRESET = 'high'

# =============================================================================
# Global State
# =============================================================================

class StreamState:
    def __init__(self):
        self.lock = threading.Lock()
        self.current_source = DEFAULT_SOURCE
        self.frame = None  # Current JPEG frame bytes
        self.frame_id = 0  # Frame counter for clients to detect new frames
        self.frame_condition = threading.Condition(self.lock)  # For proper multi-client notification
        self.running = True
        self.debug = False
        
        # Configurable settings
        self.jpeg_quality = JPEG_QUALITY
        self.scale_factor = 1.0  # 0.25 to 2.0
        self.picam_preset = DEFAULT_PICAM_PRESET
        self.picam_restart_needed = False
        
        self.stats = {
            'frames_captured': 0,
            'frames_sent': 0,
            'clients_connected': 0,
            'source_switches': 0,
            'last_frame_time': 0,
        }

state = StreamState()

# =============================================================================
# Kinect Capture
# =============================================================================

class KinectCapture:
    """Manages Kinect video capture with mode switching
    
    Note: The freenect sync API only supports RESOLUTION_MEDIUM (640x480).
    Higher resolutions require using the async API which is more complex.
    We support output scaling via OpenCV for flexibility.
    """
    
    def __init__(self):
        self.current_mode = None
        self.lock = threading.Lock()
        self.consecutive_failures = 0
        self.max_failures = 5  # Mark as unavailable after this many consecutive failures
        
    def check_availability(self):
        """Test if Kinect is actually connected and working"""
        global KINECT_AVAILABLE, SOURCES
        
        if not FREENECT_AVAILABLE or not CV2_AVAILABLE:
            KINECT_AVAILABLE = False
            SOURCES = get_available_sources()
            return False
            
        try:
            # Try to get a single frame to test connection
            data = freenect.sync_get_video(0, freenect.VIDEO_RGB)
            if data is not None:
                KINECT_AVAILABLE = True
                SOURCES = get_available_sources()
                self.consecutive_failures = 0
                return True
        except Exception as e:
            if state.debug:
                print(f"Kinect availability check failed: {e}")
        
        KINECT_AVAILABLE = False
        SOURCES = get_available_sources()
        return False
        
    def _mark_unavailable(self):
        """Mark Kinect as unavailable and switch to picam"""
        global KINECT_AVAILABLE, SOURCES
        
        KINECT_AVAILABLE = False
        SOURCES = get_available_sources()
        
        # Auto-switch to picam if currently on a Kinect source
        if state.current_source in KINECT_SOURCES:
            print(f"Kinect unavailable, auto-switching from {state.current_source} to picam")
            state.current_source = 'picam'
        
    def get_frame(self, mode, scale_factor=1.0):
        """Get a frame from Kinect in the specified mode.
        
        Args:
            mode: 'rgb', 'ir', or 'depth'
            scale_factor: Output scaling (1.0 = native 640x480)
            
        Returns:
            numpy array (BGR format ready for cv2) or None
        """
        if not FREENECT_AVAILABLE or not CV2_AVAILABLE or not KINECT_AVAILABLE:
            return None
            
        try:
            with self.lock:
                if mode == 'rgb':
                    data = freenect.sync_get_video(0, freenect.VIDEO_RGB)
                    if data is None:
                        self.consecutive_failures += 1
                        if self.consecutive_failures >= self.max_failures:
                            self._mark_unavailable()
                        return None
                    frame = data[0]
                    # Convert RGB to BGR for OpenCV
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    
                elif mode == 'ir':
                    data = freenect.sync_get_video(0, freenect.VIDEO_IR_8BIT)
                    if data is None:
                        self.consecutive_failures += 1
                        if self.consecutive_failures >= self.max_failures:
                            self._mark_unavailable()
                        return None
                    frame = data[0]
                    # IR is grayscale, convert to BGR
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                    
                elif mode == 'depth':
                    data = freenect.sync_get_depth()
                    if data is None:
                        self.consecutive_failures += 1
                        if self.consecutive_failures >= self.max_failures:
                            self._mark_unavailable()
                        return None
                    frame = data[0]
                    # Normalize depth and apply colormap
                    np.clip(frame, 0, 2047, out=frame)
                    frame = (frame >> 3).astype(np.uint8)
                    frame = cv2.applyColorMap(frame, cv2.COLORMAP_JET)
                else:
                    return None
                
                # Success - reset failure counter
                self.consecutive_failures = 0
                    
                # Apply scaling if needed
                if scale_factor != 1.0 and frame is not None:
                    new_width = int(KINECT_WIDTH * scale_factor)
                    new_height = int(KINECT_HEIGHT * scale_factor)
                    frame = cv2.resize(frame, (new_width, new_height), 
                                       interpolation=cv2.INTER_LINEAR)
                
                return frame
                    
        except Exception as e:
            if state.debug:
                print(f"Kinect capture error ({mode}): {e}")
            self.consecutive_failures += 1
            if self.consecutive_failures >= self.max_failures:
                self._mark_unavailable()
            return None
            
        return None
        
    def stop(self):
        """Clean up Kinect resources"""
        if FREENECT_AVAILABLE:
            try:
                freenect.sync_stop()
            except:
                pass

kinect = KinectCapture()

# =============================================================================
# Pi Camera Capture (via subprocess)
# =============================================================================

class PiCameraCapture:
    """Manages Pi Camera capture via rpicam-vid subprocess"""
    
    def __init__(self):
        self.process = None
        self.lock = threading.Lock()
        self.frame_buffer = None
        self.capture_thread = None
        self.running = False
        self.current_preset = None
        
    def start(self, preset='high'):
        """Start the Pi camera capture subprocess
        
        Args:
            preset: Resolution preset ('low', 'medium', 'high', 'full')
        """
        with self.lock:
            # Check if we need to restart with new settings
            if self.process is not None:
                if self.current_preset == preset:
                    return True
                # Different preset requested, need to restart
                self._stop_internal()
                
            settings = PICAM_PRESETS.get(preset, PICAM_PRESETS['high'])
            
            # Find available camera command
            cmd = None
            for candidate in ['rpicam-vid', 'libcamera-vid']:
                try:
                    subprocess.run([candidate, '--help'], 
                                   capture_output=True, timeout=2)
                    cmd = candidate
                    break
                except:
                    continue
                    
            if cmd is None:
                print("Warning: No Pi camera command available")
                return False
                
            try:
                # Start camera streaming MJPEG to stdout
                # --nopreview (-n) disables the native preview window
                self.process = subprocess.Popen([
                    cmd,
                    '-t', '0',  # Run forever
                    '-n',       # No preview window
                    '--width', str(settings['width']),
                    '--height', str(settings['height']),
                    '--framerate', str(settings['fps']),
                    '--codec', 'mjpeg',
                    '-o', '-'  # Output to stdout
                ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                
                self.running = True
                self.current_preset = preset
                self.capture_thread = threading.Thread(target=self._capture_loop)
                self.capture_thread.daemon = True
                self.capture_thread.start()
                
                print(f"Started Pi camera: {cmd} @ {settings['width']}x{settings['height']} {settings['fps']}fps ({preset})")
                return True
                
            except Exception as e:
                print(f"Failed to start Pi camera: {e}")
                return False
                
    def _capture_loop(self):
        """Read MJPEG frames from subprocess stdout"""
        buffer = b''
        while self.running and self.process:
            try:
                chunk = self.process.stdout.read(4096)
                if not chunk:
                    break
                buffer += chunk
                
                # Find JPEG boundaries (SOI and EOI markers)
                while True:
                    soi = buffer.find(b'\xff\xd8')
                    if soi == -1:
                        buffer = b''
                        break
                        
                    eoi = buffer.find(b'\xff\xd9', soi)
                    if eoi == -1:
                        # Keep from SOI onwards
                        buffer = buffer[soi:]
                        break
                        
                    # Extract complete JPEG
                    jpeg_data = buffer[soi:eoi+2]
                    buffer = buffer[eoi+2:]
                    
                    with self.lock:
                        self.frame_buffer = jpeg_data
                        
            except Exception as e:
                if state.debug:
                    print(f"Pi camera read error: {e}")
                break
                
    def get_frame(self):
        """Get the latest JPEG frame from Pi camera
        
        Returns:
            JPEG bytes or None
        """
        with self.lock:
            return self.frame_buffer
    
    def _stop_internal(self):
        """Internal stop without lock (caller must hold lock)"""
        self.running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except:
                self.process.kill()
            self.process = None
        self.frame_buffer = None
        self.current_preset = None
            
    def stop(self):
        """Stop the Pi camera subprocess"""
        with self.lock:
            self._stop_internal()

picam = PiCameraCapture()

# =============================================================================
# Frame Capture Thread
# =============================================================================

def capture_thread():
    """Main capture loop - gets frames from current source"""
    
    last_source = None
    last_picam_preset = None
    
    while state.running:
        try:
            source = state.current_source
            scale = state.scale_factor
            quality = state.jpeg_quality
            picam_preset = state.picam_preset
            
            # Handle source changes
            if source != last_source:
                print(f"Switching source: {last_source} -> {source}")
                
                # Stop Pi camera if switching away
                if last_source == 'picam':
                    picam.stop()
                    
                # Start Pi camera if switching to it
                if source == 'picam':
                    picam.start(picam_preset)
                    last_picam_preset = picam_preset
                    
                last_source = source
                state.stats['source_switches'] += 1
                
            # Handle Pi camera preset changes while active
            elif source == 'picam' and picam_preset != last_picam_preset:
                print(f"Changing Pi camera preset: {last_picam_preset} -> {picam_preset}")
                picam.start(picam_preset)  # Will restart with new settings
                last_picam_preset = picam_preset
                
            # Capture frame based on source
            jpeg_bytes = None
            
            if source == 'kinect_rgb':
                frame = kinect.get_frame('rgb', scale)
                if frame is not None:
                    _, jpeg_bytes = cv2.imencode('.jpg', frame, 
                        [cv2.IMWRITE_JPEG_QUALITY, quality])
                    jpeg_bytes = jpeg_bytes.tobytes()
                    
            elif source == 'kinect_ir':
                frame = kinect.get_frame('ir', scale)
                if frame is not None:
                    _, jpeg_bytes = cv2.imencode('.jpg', frame,
                        [cv2.IMWRITE_JPEG_QUALITY, quality])
                    jpeg_bytes = jpeg_bytes.tobytes()
                    
            elif source == 'kinect_depth':
                frame = kinect.get_frame('depth', scale)
                if frame is not None:
                    _, jpeg_bytes = cv2.imencode('.jpg', frame,
                        [cv2.IMWRITE_JPEG_QUALITY, quality])
                    jpeg_bytes = jpeg_bytes.tobytes()
                    
            elif source == 'picam':
                jpeg_bytes = picam.get_frame()
                
            # Update shared state
            if jpeg_bytes:
                with state.frame_condition:
                    state.frame = jpeg_bytes
                    state.frame_id += 1
                    state.stats['frames_captured'] += 1
                    state.stats['last_frame_time'] = time.time()
                    state.frame_condition.notify_all()  # Wake all waiting clients
                
            # Rate limiting
            time.sleep(FRAME_INTERVAL)
            
        except Exception as e:
            if state.debug:
                print(f"Capture error: {e}")
            time.sleep(0.1)
            
    # Cleanup
    kinect.stop()
    picam.stop()

# =============================================================================
# HTTP MJPEG Streaming Server
# =============================================================================

class StreamHandler(BaseHTTPRequestHandler):
    """HTTP handler for MJPEG streaming and web viewer"""
    
    def log_message(self, format, *args):
        if state.debug:
            print(f"HTTP: {args[0]}")
            
    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.send_viewer_page()
        elif self.path == '/stream.mjpg' or self.path == '/stream':
            self.send_mjpeg_stream()
        elif self.path == '/status':
            self.send_status()
        elif self.path == '/favicon.ico':
            self.send_error(404)
        else:
            self.send_error(404)
            
    def send_viewer_page(self):
        """Send HTML page with embedded MJPEG viewer"""
        html = f'''<!DOCTYPE html>
<html>
<head>
    <title>Video Multiplexer</title>
    <style>
        body {{ 
            font-family: Arial, sans-serif; 
            background: #1a1a2e; 
            color: #eee;
            margin: 0;
            padding: 20px;
        }}
        h1 {{ color: #00d9ff; margin-bottom: 10px; }}
        .container {{ max-width: 1300px; margin: 0 auto; }}
        .video-container {{
            background: #000;
            border-radius: 8px;
            overflow: hidden;
            margin-bottom: 20px;
        }}
        img {{ 
            width: 100%; 
            max-width: 1280px;
            display: block;
        }}
        .controls {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            margin-bottom: 15px;
            align-items: center;
        }}
        .control-group {{
            display: flex;
            gap: 8px;
            align-items: center;
            background: #16213e;
            padding: 8px 12px;
            border-radius: 6px;
        }}
        .control-group label {{
            font-size: 14px;
            color: #aaa;
        }}
        button {{
            padding: 10px 20px;
            font-size: 14px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            background: #16213e;
            color: #eee;
            transition: all 0.2s;
        }}
        button:hover {{ background: #0f3460; }}
        button.active {{ background: #00d9ff; color: #000; }}
        button:disabled {{ background: #333; color: #666; cursor: not-allowed; }}
        button:disabled:hover {{ background: #333; }}
        select, input[type="range"] {{
            background: #0f3460;
            color: #eee;
            border: 1px solid #00d9ff;
            border-radius: 4px;
            padding: 6px;
        }}
        input[type="range"] {{ width: 100px; }}
        .status {{
            background: #16213e;
            padding: 15px;
            border-radius: 8px;
            font-family: monospace;
            font-size: 13px;
        }}
        .status span {{ color: #00d9ff; }}
        h3 {{ margin: 15px 0 10px 0; color: #00d9ff; font-size: 14px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🎥 Video Multiplexer</h1>
        <div class="video-container">
            <img id="stream" src="/stream.mjpg" alt="Video Stream">
        </div>
        
        <h3>Video Source</h3>
        <div class="controls">
            <button onclick="switchSource('kinect_rgb')" id="btn-kinect_rgb">Kinect RGB</button>
            <button onclick="switchSource('kinect_ir')" id="btn-kinect_ir">Kinect IR</button>
            <button onclick="switchSource('kinect_depth')" id="btn-kinect_depth">Kinect Depth</button>
            <button onclick="switchSource('picam')" id="btn-picam">Pi Camera</button>
        </div>
        
        <h3>Quality & Resolution</h3>
        <div class="controls">
            <div class="control-group">
                <label>JPEG Quality:</label>
                <input type="range" id="quality" min="10" max="100" value="70" onchange="setQuality(this.value)">
                <span id="quality-val">70</span>
            </div>
            <div class="control-group">
                <label>Kinect Scale:</label>
                <select id="scale" onchange="setScale(this.value)">
                    <option value="0.5">320x240 (0.5x)</option>
                    <option value="0.75">480x360 (0.75x)</option>
                    <option value="1.0" selected>640x480 (1.0x)</option>
                    <option value="1.5">960x720 (1.5x)</option>
                    <option value="2.0">1280x960 (2.0x)</option>
                </select>
            </div>
            <div class="control-group">
                <label>Pi Cam Res:</label>
                <select id="picam_res" onchange="setPicamRes(this.value)">
                    <option value="low">640x480 (low)</option>
                    <option value="medium">1280x720 (medium)</option>
                    <option value="high" selected>1280x800 (high)</option>
                    <option value="full">1920x1080 (full)</option>
                </select>
            </div>
        </div>
        
        <div class="status" id="status">
            Source: <span id="current-source">loading...</span> | 
            Kinect: <span id="kinect-status">-</span> |
            Resolution: <span id="resolution">-</span> | 
            Quality: <span id="jpeg-quality">-</span> |
            Frames: <span id="frames">0</span> |
            Clients: <span id="clients">0</span>
        </div>
    </div>
    <script>
        function switchSource(source) {{
            fetch('/switch?source=' + source).then(r => r.text());
            document.querySelectorAll('.controls button').forEach(b => b.classList.remove('active'));
            document.getElementById('btn-' + source).classList.add('active');
        }}
        
        function setQuality(val) {{
            document.getElementById('quality-val').textContent = val;
            fetch('/switch?quality=' + val);
        }}
        
        function setScale(val) {{
            fetch('/switch?scale=' + val);
        }}
        
        function setPicamRes(val) {{
            fetch('/switch?picam_res=' + val);
        }}
        
        function updateStatus() {{
            fetch('/status')
                .then(r => r.json())
                .then(data => {{
                    document.getElementById('current-source').textContent = data.source;
                    document.getElementById('resolution').textContent = data.resolution;
                    document.getElementById('jpeg-quality').textContent = data.jpeg_quality;
                    document.getElementById('frames').textContent = data.frames_captured;
                    document.getElementById('clients').textContent = data.clients_connected;
                    
                    // Show Kinect status
                    let kinectStatus = document.getElementById('kinect-status');
                    if (data.kinect_available) {{
                        kinectStatus.textContent = 'OK';
                        kinectStatus.style.color = '#00ff00';
                    }} else {{
                        kinectStatus.textContent = 'N/A';
                        kinectStatus.style.color = '#ff6666';
                    }}
                    
                    // Enable/disable Kinect buttons based on availability
                    ['kinect_rgb', 'kinect_ir', 'kinect_depth'].forEach(src => {{
                        let btn = document.getElementById('btn-' + src);
                        if (btn) btn.disabled = !data.kinect_available;
                    }});
                    
                    // Sync UI controls
                    document.getElementById('quality').value = data.jpeg_quality;
                    document.getElementById('quality-val').textContent = data.jpeg_quality;
                    document.getElementById('scale').value = data.scale_factor;
                    document.getElementById('picam_res').value = data.picam_preset;
                    
                    // Highlight active source
                    document.querySelectorAll('.controls button').forEach(b => b.classList.remove('active'));
                    let btn = document.getElementById('btn-' + data.source);
                    if (btn) btn.classList.add('active');
                }});
        }}
        
        setInterval(updateStatus, 2000);
        updateStatus();
    </script>
</body>
</html>'''
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', len(html))
        self.end_headers()
        self.wfile.write(html.encode())
        
    def send_mjpeg_stream(self):
        """Send continuous MJPEG stream"""
        self.send_response(200)
        self.send_header('Content-Type', 
                         'multipart/x-mixed-replace; boundary=--jpgboundary')
        self.send_header('Cache-Control', 'no-cache, private')
        self.send_header('Pragma', 'no-cache')
        self.end_headers()
        
        with state.lock:
            state.stats['clients_connected'] += 1
            
        last_frame_id = 0
            
        try:
            while state.running:
                # Wait for a new frame
                with state.frame_condition:
                    # Wait until we have a new frame (frame_id changed)
                    while state.frame_id == last_frame_id and state.running:
                        if not state.frame_condition.wait(timeout=1.0):
                            # Timeout - check if still running
                            continue
                    
                    if not state.running:
                        break
                        
                    frame = state.frame
                    last_frame_id = state.frame_id
                    
                if frame is None:
                    continue
                    
                try:
                    self.wfile.write(b'--jpgboundary\r\n')
                    self.wfile.write(b'Content-Type: image/jpeg\r\n')
                    self.wfile.write(f'Content-Length: {len(frame)}\r\n\r\n'.encode())
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
                    self.wfile.flush()
                    
                    with state.lock:
                        state.stats['frames_sent'] += 1
                        
                except (BrokenPipeError, ConnectionResetError):
                    break
                
        finally:
            with state.lock:
                state.stats['clients_connected'] -= 1
                
    def send_status(self):
        """Send JSON status"""
        import json
        with state.lock:
            # Calculate current resolution
            if state.current_source == 'picam':
                preset = PICAM_PRESETS.get(state.picam_preset, PICAM_PRESETS['high'])
                resolution = f"{preset['width']}x{preset['height']}"
            else:
                # Kinect with scaling
                w = int(KINECT_WIDTH * state.scale_factor)
                h = int(KINECT_HEIGHT * state.scale_factor)
                resolution = f"{w}x{h}"
                
            data = {
                'source': state.current_source,
                'available_sources': SOURCES,
                'kinect_available': KINECT_AVAILABLE,
                'resolution': resolution,
                'jpeg_quality': state.jpeg_quality,
                'scale_factor': state.scale_factor,
                'picam_preset': state.picam_preset,
                'picam_presets': list(PICAM_PRESETS.keys()),
                'frames_captured': state.stats['frames_captured'],
                'frames_sent': state.stats['frames_sent'],
                'clients_connected': state.stats['clients_connected'],
                'source_switches': state.stats['source_switches'],
            }
        
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)
        
    def do_POST(self):
        """Handle source/settings switch via POST (alternative to TCP control)"""
        if self.path.startswith('/switch'):
            # Parse query string
            if '?' in self.path:
                query = self.path.split('?')[1]
                params = dict(p.split('=') for p in query.split('&') if '=' in p)
                
                response_parts = []
                
                # Handle source switch
                source = params.get('source', '')
                if source:
                    if source in ALL_SOURCES:
                        # Check if trying to switch to Kinect when unavailable
                        if source in KINECT_SOURCES and not KINECT_AVAILABLE:
                            self.send_response(400)
                            self.end_headers()
                            self.wfile.write(f'ERROR: Kinect unavailable. Only picam is available.\n'.encode())
                            return
                        state.current_source = source
                        response_parts.append(f"source={source}")
                    else:
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(f'ERROR: Unknown source. Use: {SOURCES}\n'.encode())
                        return
                
                # Handle quality
                quality = params.get('quality', '')
                if quality:
                    try:
                        q = int(quality)
                        if 1 <= q <= 100:
                            state.jpeg_quality = q
                            response_parts.append(f"quality={q}")
                        else:
                            raise ValueError("out of range")
                    except:
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(b'ERROR: quality must be 1-100\n')
                        return
                        
                # Handle scale
                scale = params.get('scale', '')
                if scale:
                    try:
                        s = float(scale)
                        if 0.25 <= s <= 2.0:
                            state.scale_factor = s
                            response_parts.append(f"scale={s}")
                        else:
                            raise ValueError("out of range")
                    except:
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(b'ERROR: scale must be 0.25-2.0\n')
                        return
                        
                # Handle picam_res
                picam_res = params.get('picam_res', '')
                if picam_res:
                    if picam_res in PICAM_PRESETS:
                        state.picam_preset = picam_res
                        response_parts.append(f"picam_res={picam_res}")
                    else:
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(f'ERROR: picam_res must be: {list(PICAM_PRESETS.keys())}\n'.encode())
                        return
                
                if response_parts:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(f'OK: {", ".join(response_parts)}\n'.encode())
                else:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'ERROR: No valid parameters. Use: source, quality, scale, picam_res\n')
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'ERROR: Missing parameters\n')
        else:
            self.send_error(404)
            
    # Also handle GET for /switch for convenience
    do_GET_original = do_GET
    def do_GET(self):
        if self.path.startswith('/switch'):
            self.do_POST()
        else:
            self.do_GET_original()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server for handling multiple clients"""
    daemon_threads = True

# =============================================================================
# TCP Control Server (for programmatic control)
# =============================================================================

def control_server():
    """TCP control server for source switching commands"""
    
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(('0.0.0.0', CONTROL_PORT))
    server.listen(5)
    server.settimeout(1.0)
    
    print(f"Control server listening on port {CONTROL_PORT}")
    
    while state.running:
        try:
            client, addr = server.accept()
            print(f"Control connection from {addr}")
            threading.Thread(target=handle_control_client, 
                           args=(client,), daemon=True).start()
        except socket.timeout:
            continue
        except Exception as e:
            if state.debug:
                print(f"Control server error: {e}")
                
    server.close()


def handle_control_client(client):
    """Handle a control client connection"""
    try:
        client.settimeout(30.0)
        client.send(b"Video Multiplexer Control\n")
        client.send(f"Current source: {state.current_source}\n".encode())
        client.send(f"Available: {', '.join(SOURCES)}\n".encode())
        client.send(b"Commands: <source>, quality <1-100>, scale <0.25-2.0>, picam_res <preset>, status, help\n")
        client.send(b"> ")
        
        while state.running:
            data = client.recv(1024)
            if not data:
                break
                
            cmd = data.decode('utf-8').strip()
            cmd_lower = cmd.lower()
            parts = cmd.split()
            
            if cmd_lower in ALL_SOURCES:
                # Check if trying to switch to Kinect when unavailable
                if cmd_lower in KINECT_SOURCES and not KINECT_AVAILABLE:
                    client.send(b"ERROR: Kinect unavailable. Only picam is available.\n> ")
                else:
                    old_source = state.current_source
                    state.current_source = cmd_lower
                    client.send(f"OK: Switched from {old_source} to {cmd_lower}\n> ".encode())
                
            elif parts and parts[0].lower() == 'quality':
                if len(parts) == 2:
                    try:
                        q = int(parts[1])
                        if 1 <= q <= 100:
                            state.jpeg_quality = q
                            client.send(f"OK: JPEG quality set to {q}\n> ".encode())
                        else:
                            client.send(b"ERROR: quality must be 1-100\n> ")
                    except ValueError:
                        client.send(b"ERROR: quality must be a number 1-100\n> ")
                else:
                    client.send(f"Current quality: {state.jpeg_quality} (usage: quality <1-100>)\n> ".encode())
                    
            elif parts and parts[0].lower() == 'scale':
                if len(parts) == 2:
                    try:
                        s = float(parts[1])
                        if 0.25 <= s <= 2.0:
                            state.scale_factor = s
                            w = int(KINECT_WIDTH * s)
                            h = int(KINECT_HEIGHT * s)
                            client.send(f"OK: Scale set to {s} (Kinect output: {w}x{h})\n> ".encode())
                        else:
                            client.send(b"ERROR: scale must be 0.25-2.0\n> ")
                    except ValueError:
                        client.send(b"ERROR: scale must be a number 0.25-2.0\n> ")
                else:
                    client.send(f"Current scale: {state.scale_factor} (usage: scale <0.25-2.0>)\n> ".encode())
                    
            elif parts and parts[0].lower() == 'picam_res':
                if len(parts) == 2:
                    preset = parts[1].lower()
                    if preset in PICAM_PRESETS:
                        state.picam_preset = preset
                        p = PICAM_PRESETS[preset]
                        client.send(f"OK: Pi camera preset set to {preset} ({p['width']}x{p['height']} @ {p['fps']}fps)\n> ".encode())
                    else:
                        client.send(f"ERROR: preset must be one of: {list(PICAM_PRESETS.keys())}\n> ".encode())
                else:
                    client.send(f"Current preset: {state.picam_preset} (options: {list(PICAM_PRESETS.keys())})\n> ".encode())
                
            elif cmd_lower == 'status':
                with state.lock:
                    # Calculate current resolution
                    if state.current_source == 'picam':
                        preset = PICAM_PRESETS.get(state.picam_preset, PICAM_PRESETS['high'])
                        resolution = f"{preset['width']}x{preset['height']}"
                    else:
                        w = int(KINECT_WIDTH * state.scale_factor)
                        h = int(KINECT_HEIGHT * state.scale_factor)
                        resolution = f"{w}x{h}"
                        
                    client.send(f"Source: {state.current_source}\n".encode())
                    client.send(f"Resolution: {resolution}\n".encode())
                    client.send(f"JPEG Quality: {state.jpeg_quality}\n".encode())
                    client.send(f"Scale Factor: {state.scale_factor}\n".encode())
                    client.send(f"Pi Cam Preset: {state.picam_preset}\n".encode())
                    client.send(f"Frames: {state.stats['frames_captured']}\n".encode())
                    client.send(f"Clients: {state.stats['clients_connected']}\n> ".encode())
                    
            elif cmd_lower == 'help':
                client.send(b"Commands:\n")
                client.send(f"  Sources: {', '.join(SOURCES)}\n".encode())
                client.send(b"  quality <1-100>       - Set JPEG compression (default 70)\n")
                client.send(b"  scale <0.25-2.0>      - Scale Kinect output (default 1.0)\n")
                client.send(f"  picam_res <preset>    - Set Pi camera resolution: {list(PICAM_PRESETS.keys())}\n".encode())
                client.send(b"  status                - Show current settings\n")
                client.send(b"  quit                  - Disconnect\n")
                client.send(b"\nResolution Info:\n")
                client.send(b"  Kinect: 640x480 native (use 'scale' to resize)\n")
                for name, p in PICAM_PRESETS.items():
                    client.send(f"  picam {name}: {p['width']}x{p['height']} @ {p['fps']}fps\n".encode())
                client.send(b"> ")
                
            elif cmd_lower in ['quit', 'exit', 'q']:
                client.send(b"Goodbye!\n")
                break
                
            elif cmd_lower == '':
                client.send(b"> ")
                
            else:
                client.send(f"Unknown: {cmd}. Type 'help' for commands.\n> ".encode())
                
    except Exception as e:
        if state.debug:
            print(f"Control client error: {e}")
    finally:
        client.close()

# =============================================================================
# Main Entry Point
# =============================================================================

# Global server reference for clean shutdown
_http_server = None

def signal_handler(sig, frame):
    print("\nShutting down...")
    state.running = False
    # Shutdown HTTP server to unblock serve_forever()
    if _http_server:
        _http_server.shutdown()

def main():
    global KINECT_AVAILABLE, SOURCES
    
    parser = argparse.ArgumentParser(description='Unified Video Multiplexer')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--source', default=None, 
                        choices=ALL_SOURCES, help='Initial video source')
    parser.add_argument('--port', type=int, default=STREAM_PORT,
                        help='HTTP stream port')
    parser.add_argument('--quality', type=int, default=JPEG_QUALITY,
                        help='JPEG quality 1-100 (default: 70)')
    parser.add_argument('--scale', type=float, default=1.0,
                        help='Kinect output scale 0.25-2.0 (default: 1.0)')
    parser.add_argument('--picam-res', default=DEFAULT_PICAM_PRESET,
                        choices=list(PICAM_PRESETS.keys()),
                        help='Pi camera resolution preset')
    args = parser.parse_args()
    
    state.debug = args.debug
    state.jpeg_quality = max(1, min(100, args.quality))
    state.scale_factor = max(0.25, min(2.0, args.scale))
    state.picam_preset = args.picam_res
    
    # Check if Kinect is actually available at startup
    print("Checking Kinect availability...")
    kinect_ok = kinect.check_availability()
    
    # Determine initial source
    requested_source = args.source
    if requested_source is None:
        # No source specified, use default based on availability
        requested_source = 'kinect_rgb' if KINECT_AVAILABLE else 'picam'
    elif requested_source in KINECT_SOURCES and not KINECT_AVAILABLE:
        # Requested Kinect source but Kinect unavailable
        print(f"Warning: Requested source '{requested_source}' unavailable, defaulting to picam")
        requested_source = 'picam'
    
    state.current_source = requested_source
    
    # Set up signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Calculate initial resolution for display
    if state.current_source == 'picam':
        p = PICAM_PRESETS[args.picam_res]
        res_str = f"{p['width']}x{p['height']}"
    else:
        w = int(KINECT_WIDTH * args.scale)
        h = int(KINECT_HEIGHT * args.scale)
        res_str = f"{w}x{h}"
    
    print("=" * 60)
    print("Video Multiplexer Starting")
    print("=" * 60)
    print(f"  Stream URL:     http://0.0.0.0:{args.port}/stream.mjpg")
    print(f"  Web Viewer:     http://0.0.0.0:{args.port}/")
    print(f"  Control Port:   {CONTROL_PORT} (TCP)")
    print(f"  Initial Source: {state.current_source}")
    print(f"  Kinect:         {'Available' if KINECT_AVAILABLE else 'NOT AVAILABLE'}")
    print(f"  Resolution:     {res_str}")
    print(f"  JPEG Quality:   {state.jpeg_quality}")
    print(f"  Available:      {', '.join(SOURCES)}")
    print("=" * 60)
    if KINECT_AVAILABLE:
        print("Resolution Notes:")
        print(f"  Kinect: 640x480 native (scale: {args.scale}x -> {int(640*args.scale)}x{int(480*args.scale)})")
    for name, p in PICAM_PRESETS.items():
        marker = " <--" if name == args.picam_res else ""
        print(f"  Pi Cam {name}: {p['width']}x{p['height']} @ {p['fps']}fps{marker}")
    print("=" * 60)
    
    if not CV2_AVAILABLE:
        print("ERROR: OpenCV required. Install with: pip install opencv-python")
        sys.exit(1)
        
    if not KINECT_AVAILABLE:
        print("INFO: Kinect not detected, using Pi Camera only")
        
    # Start capture thread
    capture_t = threading.Thread(target=capture_thread, daemon=True)
    capture_t.start()
    
    # Start control server
    control_t = threading.Thread(target=control_server, daemon=True)
    control_t.start()
    
    # Start HTTP server (blocks)
    global _http_server
    try:
        _http_server = ThreadedHTTPServer(('0.0.0.0', args.port), StreamHandler)
        print(f"HTTP server started on port {args.port}")
        _http_server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        state.running = False
        if _http_server:
            _http_server.server_close()
        # Give threads a moment to clean up
        kinect.stop()
        picam.stop()
        print("Server stopped")

if __name__ == '__main__':
    main()
