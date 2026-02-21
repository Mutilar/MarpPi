"""
Configuration constants for the video multiplexer.
"""

import os
import sys

# =============================================================================
# Port Configuration
# =============================================================================

STREAM_PORT = 5600           # Main HTTP MJPEG stream
SECONDARY_STREAM_PORT = 5601  # Secondary TCP raw stream
CONTROL_PORT = 5603          # TCP control server

# =============================================================================
# Video Sources
# =============================================================================

ALL_SOURCES = ['kinect_rgb', 'kinect_ir', 'kinect_depth', 'picam']
KINECT_SOURCES = ['kinect_rgb', 'kinect_ir', 'kinect_depth']
DEFAULT_SOURCE = 'picam'

# =============================================================================
# Stream Settings
# =============================================================================

JPEG_QUALITY = 70          # 1-100, higher = better quality, more bandwidth
TARGET_FPS = 15
FRAME_INTERVAL = 1.0 / TARGET_FPS

# =============================================================================
# Kinect Configuration
# =============================================================================

# Kinect native resolution (fixed by sync API - RESOLUTION_MEDIUM)
KINECT_WIDTH = 640
KINECT_HEIGHT = 480

# =============================================================================
# Pi Camera Configuration
# =============================================================================

PICAM_PRESETS = {
    'low':    {'width': 640,  'height': 480,  'fps': 30},
    'medium': {'width': 1280, 'height': 720,  'fps': 24},
    'high':   {'width': 1280, 'height': 800,  'fps': 24},
    'full':   {'width': 1920, 'height': 1080, 'fps': 15},
}
DEFAULT_PICAM_PRESET = 'high'

# =============================================================================
# Library Path Configuration
# =============================================================================

# Add libfreenect python wrapper to path
LIBFREENECT_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '../../libfreenect/build/wrappers/python/python3'))

if LIBFREENECT_PATH not in sys.path:
    sys.path.append(LIBFREENECT_PATH)

# =============================================================================
# Dependency Availability
# =============================================================================

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
# This gets updated dynamically based on actual hardware detection
KINECT_AVAILABLE = FREENECT_AVAILABLE


def get_available_sources():
    """Return list of currently available sources based on hardware."""
    global KINECT_AVAILABLE
    if KINECT_AVAILABLE:
        return ALL_SOURCES[:]
    else:
        return ['picam']


def update_kinect_availability(available: bool):
    """Update the global Kinect availability flag."""
    global KINECT_AVAILABLE
    KINECT_AVAILABLE = available
