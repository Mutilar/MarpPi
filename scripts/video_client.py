#!/usr/bin/env python3
"""
Video Multiplexer Client
========================

A simple client to view the video stream and send control commands.

Usage:
    # View stream in OpenCV window
    python3 video_client.py --host 192.168.1.100
    
    # Just send a command
    python3 video_client.py --host 192.168.1.100 --command kinect_ir
    
    # Interactive control mode
    python3 video_client.py --host 192.168.1.100 --control
"""

import argparse
import socket
import sys
import threading
import time
import urllib.request

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


def send_command(host, port, command):
    """Send a command to the control server"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5.0)
        sock.connect((host, port))
        
        # Read welcome message
        sock.recv(1024)
        
        # Send command
        sock.send(f"{command}\n".encode())
        response = sock.recv(1024).decode()
        print(f"Response: {response.strip()}")
        
        sock.close()
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False


def interactive_control(host, port):
    """Interactive control session"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(30.0)
        sock.connect((host, port))
        
        # Read welcome
        print(sock.recv(1024).decode(), end='')
        
        while True:
            try:
                cmd = input()
                if cmd.lower() in ['quit', 'exit', 'q']:
                    break
                sock.send(f"{cmd}\n".encode())
                print(sock.recv(1024).decode(), end='')
            except EOFError:
                break
                
        sock.close()
    except Exception as e:
        print(f"Error: {e}")


def view_stream(host, stream_port, control_port):
    """View the MJPEG stream in an OpenCV window"""
    if not CV2_AVAILABLE:
        print("OpenCV not available. Install with: pip install opencv-python")
        return
        
    url = f"http://{host}:{stream_port}/stream.mjpg"
    print(f"Connecting to {url}...")
    print("Controls:")
    print("  1 = Kinect RGB")
    print("  2 = Kinect IR")
    print("  3 = Kinect Depth")
    print("  4 = Pi Camera")
    print("  q = Quit")
    
    try:
        stream = urllib.request.urlopen(url, timeout=10)
    except Exception as e:
        print(f"Failed to connect: {e}")
        return
    
    cv2.namedWindow('Video Stream', cv2.WINDOW_NORMAL)
    
    buffer = b''
    while True:
        # Read chunk
        chunk = stream.read(4096)
        if not chunk:
            break
        buffer += chunk
        
        # Find JPEG frame
        start = buffer.find(b'\xff\xd8')
        end = buffer.find(b'\xff\xd9')
        
        if start != -1 and end != -1 and end > start:
            jpg = buffer[start:end+2]
            buffer = buffer[end+2:]
            
            # Decode and display
            frame = cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
            if frame is not None:
                cv2.imshow('Video Stream', frame)
                
        # Handle key presses
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('1'):
            send_command(host, control_port, 'kinect_rgb')
        elif key == ord('2'):
            send_command(host, control_port, 'kinect_ir')
        elif key == ord('3'):
            send_command(host, control_port, 'kinect_depth')
        elif key == ord('4'):
            send_command(host, control_port, 'picam')
            
    cv2.destroyAllWindows()


def main():
    parser = argparse.ArgumentParser(description='Video Multiplexer Client')
    parser.add_argument('--host', default='localhost', help='Server hostname/IP')
    parser.add_argument('--port', type=int, default=5600, help='Stream port')
    parser.add_argument('--control-port', type=int, default=5603, help='Control port')
    parser.add_argument('--command', help='Send a single command and exit')
    parser.add_argument('--control', action='store_true', help='Interactive control mode')
    parser.add_argument('--view', action='store_true', help='View stream (default if no other option)')
    args = parser.parse_args()
    
    if args.command:
        send_command(args.host, args.control_port, args.command)
    elif args.control:
        interactive_control(args.host, args.control_port)
    else:
        view_stream(args.host, args.port, args.control_port)


if __name__ == '__main__':
    main()
