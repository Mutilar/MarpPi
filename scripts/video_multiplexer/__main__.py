#!/usr/bin/env python3
"""
Unified Video Multiplexer for Pi + Kinect
==========================================

Multi-stream video server supporting independent source switching.

Streams:
  - Main (HTTP MJPEG): Port 5600 - Web viewer at http://<ip>:5600/
  - Secondary (TCP raw): Port 5601 - Length-prefixed JPEG frames
  
Control:
  - TCP control server: Port 5603 - Text commands for stream management
  
Video Sources:
  - kinect_rgb:   Kinect RGB camera (640x480 native, scalable)
  - kinect_ir:    Kinect IR camera (640x480 native, scalable)
  - kinect_depth: Kinect depth colorized (640x480 native, scalable)
  - picam:        Raspberry Pi Camera (configurable resolution)

Usage:
    python -m video_multiplexer [options]
    
    # Or run directly:
    python video_multiplexer/__main__.py [options]

Options:
    --debug              Enable debug output
    --main-source        Initial source for main stream
    --secondary-source   Initial source for secondary stream
    --main-port          HTTP port for main stream (default: 5600)
    --secondary-port     TCP port for secondary stream (default: 5601)
    --control-port       TCP port for control server (default: 5603)
    --quality            JPEG quality 1-100 (default: 70)
    --scale              Kinect output scale 0.25-2.0 (default: 1.0)
    --picam-res          Pi camera preset (low/medium/high/full)

Control Commands (via TCP port 5603):
    streams              List all streams
    select <stream>      Select stream to control (main/secondary)
    <source>             Switch to source (kinect_rgb, kinect_ir, kinect_depth, picam)
    quality <1-100>      Set JPEG compression
    scale <0.25-2.0>     Set Kinect output scale
    picam_res <preset>   Set Pi camera resolution
    status               Show selected stream status
    status all           Show all streams
    help                 Show help
"""

import argparse
import sys

from .config import (
    CV2_AVAILABLE,
    KINECT_AVAILABLE,
    ALL_SOURCES,
    PICAM_PRESETS,
    STREAM_PORT,
    SECONDARY_STREAM_PORT,
    CONTROL_PORT,
    KINECT_WIDTH,
)
from .manager import StreamManager
from .state import global_state
from .sources.kinect import get_kinect
from .servers.orchestrator import ServerOrchestrator


def main():
    parser = argparse.ArgumentParser(
        description='Unified Video Multiplexer with Multiple Streams',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
    # Start with defaults (main: kinect_rgb, secondary: picam)
    python -m video_multiplexer
    
    # Both streams on picam
    python -m video_multiplexer --main-source picam --secondary-source picam
    
    # High quality, scaled up
    python -m video_multiplexer --quality 90 --scale 1.5
        '''
    )
    
    parser.add_argument('--debug', action='store_true', 
                        help='Enable debug output')
    parser.add_argument('--main-source', default=None, choices=ALL_SOURCES,
                        help='Initial source for main stream')
    parser.add_argument('--secondary-source', default=None, choices=ALL_SOURCES,
                        help='Initial source for secondary stream')
    parser.add_argument('--main-port', type=int, default=STREAM_PORT,
                        help=f'HTTP port for main stream (default: {STREAM_PORT})')
    parser.add_argument('--secondary-port', type=int, default=SECONDARY_STREAM_PORT,
                        help=f'TCP port for secondary stream (default: {SECONDARY_STREAM_PORT})')
    parser.add_argument('--control-port', type=int, default=CONTROL_PORT,
                        help=f'TCP port for control server (default: {CONTROL_PORT})')
    parser.add_argument('--quality', type=int, default=70,
                        help='JPEG quality 1-100 (default: 70)')
    parser.add_argument('--scale', type=float, default=1.0,
                        help='Kinect output scale 0.25-2.0 (default: 1.0)')
    parser.add_argument('--picam-res', default='high', choices=list(PICAM_PRESETS.keys()),
                        help='Pi camera resolution preset (default: high)')
    
    args = parser.parse_args()
    
    # Check dependencies
    if not CV2_AVAILABLE:
        print("ERROR: OpenCV required. Install with: pip install opencv-python")
        sys.exit(1)
        
    # Set debug mode
    global_state.debug = args.debug
    
    # Check Kinect availability
    print("Checking Kinect availability...")
    kinect = get_kinect()
    kinect.debug = args.debug
    kinect_ok = kinect.check_availability()
    
    # Determine initial sources
    main_source = args.main_source
    secondary_source = args.secondary_source
    
    if main_source is None:
        main_source = 'kinect_rgb' if KINECT_AVAILABLE else 'picam'
    elif main_source in ['kinect_rgb', 'kinect_ir', 'kinect_depth'] and not KINECT_AVAILABLE:
        print(f"Warning: Main source '{main_source}' unavailable, using picam")
        main_source = 'picam'
        
    if secondary_source is None:
        secondary_source = 'picam'  # Default secondary to picam for diversity
    elif secondary_source in ['kinect_rgb', 'kinect_ir', 'kinect_depth'] and not KINECT_AVAILABLE:
        print(f"Warning: Secondary source '{secondary_source}' unavailable, using picam")
        secondary_source = 'picam'
        
    # Create stream manager
    manager = StreamManager()
    
    # Create streams
    main_stream = manager.create_stream('main', main_source)
    main_stream.update_settings(
        jpeg_quality=args.quality,
        scale_factor=args.scale,
        picam_preset=args.picam_res
    )
    
    secondary_stream = manager.create_stream('secondary', secondary_source)
    secondary_stream.update_settings(
        jpeg_quality=args.quality,
        scale_factor=args.scale,
        picam_preset=args.picam_res
    )
    
    # Calculate resolutions for display
    def get_resolution(source, scale, preset):
        if source == 'picam':
            p = PICAM_PRESETS[preset]
            return f"{p['width']}x{p['height']}"
        else:
            w = int(KINECT_WIDTH * scale)
            h = int(int(KINECT_WIDTH * 0.75) * scale)  # 4:3 aspect
            return f"{w}x{h}"
    
    main_res = get_resolution(main_source, args.scale, args.picam_res)
    secondary_res = get_resolution(secondary_source, args.scale, args.picam_res)
    
    # Print startup info
    print("=" * 65)
    print("Video Multiplexer v2.0 - Multi-Stream Edition")
    print("=" * 65)
    print()
    print("Streams:")
    print(f"  Main (HTTP):      http://0.0.0.0:{args.main_port}/")
    print(f"                    Source: {main_source}, Resolution: {main_res}")
    print(f"  Secondary (TCP):  0.0.0.0:{args.secondary_port}")
    print(f"                    Source: {secondary_source}, Resolution: {secondary_res}")
    print()
    print(f"Control Server:     0.0.0.0:{args.control_port} (TCP)")
    print()
    print(f"Hardware:")
    print(f"  Kinect:           {'Available' if KINECT_AVAILABLE else 'NOT AVAILABLE'}")
    print(f"  JPEG Quality:     {args.quality}")
    print(f"  Kinect Scale:     {args.scale}x")
    print(f"  Pi Cam Preset:    {args.picam_res}")
    print()
    print("=" * 65)
    print("Pi Camera Presets:")
    for name, p in PICAM_PRESETS.items():
        marker = " <-- active" if name == args.picam_res else ""
        print(f"  {name:8} {p['width']}x{p['height']} @ {p['fps']}fps{marker}")
    print("=" * 65)
    print()
    print("Control Commands (connect via: nc localhost 5603):")
    print("  select main|secondary  - Select stream")
    print("  kinect_rgb|ir|depth    - Switch to Kinect source")
    print("  picam                  - Switch to Pi Camera")
    print("  status all             - Show all streams")
    print("=" * 65)
    
    # Start capture thread
    manager.start()
    
    # Set up and start servers
    orchestrator = ServerOrchestrator(manager)
    orchestrator.add_http_stream('main', args.main_port, args.debug)
    orchestrator.add_tcp_stream('secondary', args.secondary_port, args.debug)
    orchestrator.set_control_server(args.control_port, args.debug)
    
    try:
        orchestrator.run_forever()
    finally:
        manager.stop()
        print("Server stopped")


if __name__ == '__main__':
    main()
