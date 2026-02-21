"""
Video Multiplexer Package
=========================

Unified video streaming with multiple independent streams supporting:
  - kinect_rgb:   Kinect RGB camera (640x480 native, scalable)
  - kinect_ir:    Kinect IR camera (640x480 native, scalable)
  - kinect_depth: Kinect depth colorized (640x480 native, scalable)
  - picam:        Raspberry Pi Camera (configurable resolution)

Each stream can be independently controlled and switched between sources.

Usage:
    from video_multiplexer import StreamManager, start_server
    
    manager = StreamManager()
    manager.create_stream('main', port=5600)
    manager.create_stream('secondary', port=5601, protocol='tcp')
    start_server(manager)
"""

from .config import (
    STREAM_PORT,
    SECONDARY_STREAM_PORT,
    CONTROL_PORT,
    ALL_SOURCES,
    KINECT_SOURCES,
    PICAM_PRESETS,
)
from .state import StreamState, GlobalState
from .manager import StreamManager
from .server import start_servers
from .templates import render_template, load_css, clear_cache as clear_template_cache

__version__ = '2.1.0'
__all__ = [
    'StreamManager',
    'StreamState',
    'GlobalState',
    'start_servers',
    'render_template',
    'load_css',
    'clear_template_cache',
    'STREAM_PORT',
    'SECONDARY_STREAM_PORT',
    'CONTROL_PORT',
    'ALL_SOURCES',
    'KINECT_SOURCES',
    'PICAM_PRESETS',
]
