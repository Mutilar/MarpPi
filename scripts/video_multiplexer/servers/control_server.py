"""
TCP control server for programmatic stream management.

Provides a text-based protocol for controlling multiple streams.
"""

import socket
import threading
from typing import TYPE_CHECKING, Optional

from ..config import (
    PICAM_PRESETS,
    KINECT_WIDTH,
    KINECT_HEIGHT,
    KINECT_SOURCES,
    get_available_sources,
    KINECT_AVAILABLE,
)
from ..state import global_state

if TYPE_CHECKING:
    from ..manager import StreamManager


class ControlServer:
    """TCP control server for stream management.
    
    Text-based protocol for controlling multiple video streams.
    
    Commands:
        streams                     - List all streams
        select <stream_id>          - Select stream to control
        <source>                    - Switch source (kinect_rgb, kinect_ir, kinect_depth, picam)
        quality <1-100>             - Set JPEG quality
        scale <0.25-2.0>            - Set Kinect output scale
        picam_res <preset>          - Set Pi camera resolution
        status                      - Show status of selected stream
        status all                  - Show status of all streams
        help                        - Show help
        quit                        - Disconnect
    """
    
    def __init__(self, manager: 'StreamManager', port: int, debug: bool = False):
        self.manager = manager
        self.port = port
        self.debug = debug
        self.running = False
        self.server: Optional[socket.socket] = None
        self._accept_thread: Optional[threading.Thread] = None
        
    def start(self):
        """Start the control server."""
        if self.running:
            return
            
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(('0.0.0.0', self.port))
        self.server.listen(5)
        self.server.settimeout(1.0)
        
        self.running = True
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        
        print(f"Control server listening on port {self.port}")
        
    def _accept_loop(self):
        """Accept incoming control connections."""
        while self.running and global_state.running:
            try:
                client, addr = self.server.accept()
                print(f"Control connection from {addr}")
                thread = threading.Thread(
                    target=self._handle_client, 
                    args=(client,), 
                    daemon=True
                )
                thread.start()
            except socket.timeout:
                continue
            except Exception as e:
                if self.running and self.debug:
                    print(f"Control accept error: {e}")
                    
    def _handle_client(self, client: socket.socket):
        """Handle a control client connection."""
        try:
            client.settimeout(30.0)
            
            # Welcome message
            streams = self.manager.list_streams()
            default_stream = streams[0] if streams else 'main'
            selected_stream = default_stream
            
            client.send(b"Video Multiplexer Control Server v2.0\n")
            client.send(f"Streams: {', '.join(streams)}\n".encode())
            client.send(f"Selected: {selected_stream}\n".encode())
            client.send(f"Available sources: {', '.join(get_available_sources())}\n".encode())
            client.send(b"Type 'help' for commands.\n")
            client.send(b"> ")
            
            while self.running and global_state.running:
                data = client.recv(1024)
                if not data:
                    break
                    
                cmd = data.decode('utf-8').strip()
                cmd_lower = cmd.lower()
                parts = cmd.split()
                
                if not parts:
                    client.send(b"> ")
                    continue
                    
                command = parts[0].lower()
                args = parts[1:] if len(parts) > 1 else []
                
                # Stream selection
                if command == 'streams':
                    streams = self.manager.list_streams()
                    client.send(f"Available streams: {', '.join(streams)}\n".encode())
                    client.send(f"Currently selected: {selected_stream}\n> ".encode())
                    
                elif command == 'select':
                    if args:
                        target = args[0]
                        if self.manager.get_stream(target):
                            selected_stream = target
                            client.send(f"OK: Selected stream '{target}'\n> ".encode())
                        else:
                            client.send(f"ERROR: Stream '{target}' not found\n> ".encode())
                    else:
                        client.send(f"Current: {selected_stream} (usage: select <stream_id>)\n> ".encode())
                        
                # Source switching
                elif command in get_available_sources():
                    success, msg = self.manager.switch_source(selected_stream, command)
                    if success:
                        client.send(f"OK: {msg}\n> ".encode())
                    else:
                        client.send(f"ERROR: {msg}\n> ".encode())
                        
                elif command in KINECT_SOURCES and command not in get_available_sources():
                    client.send(b"ERROR: Kinect not available\n> ")
                    
                # Quality setting
                elif command == 'quality':
                    stream = self.manager.get_stream(selected_stream)
                    if not stream:
                        client.send(f"ERROR: Stream '{selected_stream}' not found\n> ".encode())
                    elif args:
                        try:
                            q = int(args[0])
                            if 1 <= q <= 100:
                                stream.update_settings(jpeg_quality=q)
                                client.send(f"OK: JPEG quality set to {q}\n> ".encode())
                            else:
                                client.send(b"ERROR: quality must be 1-100\n> ")
                        except ValueError:
                            client.send(b"ERROR: quality must be a number 1-100\n> ")
                    else:
                        settings = stream.get_settings()
                        client.send(f"Current quality: {settings['jpeg_quality']} (usage: quality <1-100>)\n> ".encode())
                        
                # Scale setting
                elif command == 'scale':
                    stream = self.manager.get_stream(selected_stream)
                    if not stream:
                        client.send(f"ERROR: Stream '{selected_stream}' not found\n> ".encode())
                    elif args:
                        try:
                            s = float(args[0])
                            if 0.25 <= s <= 2.0:
                                stream.update_settings(scale_factor=s)
                                w = int(KINECT_WIDTH * s)
                                h = int(KINECT_HEIGHT * s)
                                client.send(f"OK: Scale set to {s} (Kinect: {w}x{h})\n> ".encode())
                            else:
                                client.send(b"ERROR: scale must be 0.25-2.0\n> ")
                        except ValueError:
                            client.send(b"ERROR: scale must be a number 0.25-2.0\n> ")
                    else:
                        settings = stream.get_settings()
                        client.send(f"Current scale: {settings['scale_factor']} (usage: scale <0.25-2.0>)\n> ".encode())
                        
                # Pi camera resolution
                elif command == 'picam_res':
                    stream = self.manager.get_stream(selected_stream)
                    if not stream:
                        client.send(f"ERROR: Stream '{selected_stream}' not found\n> ".encode())
                    elif args:
                        preset = args[0].lower()
                        if preset in PICAM_PRESETS:
                            stream.update_settings(picam_preset=preset)
                            p = PICAM_PRESETS[preset]
                            client.send(f"OK: Pi camera set to {preset} ({p['width']}x{p['height']} @ {p['fps']}fps)\n> ".encode())
                        else:
                            client.send(f"ERROR: preset must be: {list(PICAM_PRESETS.keys())}\n> ".encode())
                    else:
                        settings = stream.get_settings()
                        client.send(f"Current preset: {settings['picam_preset']} (options: {list(PICAM_PRESETS.keys())})\n> ".encode())
                        
                # Status
                elif command == 'status':
                    if args and args[0].lower() == 'all':
                        # Show all streams
                        status = self.manager.get_status()
                        client.send(f"Kinect: {'Available' if status['kinect_available'] else 'N/A'}\n".encode())
                        client.send(f"Sources: {', '.join(status['available_sources'])}\n".encode())
                        client.send(b"\n")
                        for stream_id, info in status['streams'].items():
                            marker = " <-- selected" if stream_id == selected_stream else ""
                            client.send(f"[{stream_id}]{marker}\n".encode())
                            client.send(f"  Source: {info['source']}\n".encode())
                            client.send(f"  Resolution: {info['resolution']}\n".encode())
                            client.send(f"  Quality: {info['jpeg_quality']}\n".encode())
                            client.send(f"  Frames: {info['frames_captured']}\n".encode())
                            client.send(f"  Clients: {info['clients_connected']}\n".encode())
                        client.send(b"> ")
                    else:
                        # Show selected stream
                        stream = self.manager.get_stream(selected_stream)
                        if stream:
                            settings = stream.get_settings()
                            stats = stream.get_stats()
                            
                            if settings['source'] == 'picam':
                                preset = PICAM_PRESETS.get(settings['picam_preset'], PICAM_PRESETS['high'])
                                resolution = f"{preset['width']}x{preset['height']}"
                            else:
                                w = int(KINECT_WIDTH * settings['scale_factor'])
                                h = int(KINECT_HEIGHT * settings['scale_factor'])
                                resolution = f"{w}x{h}"
                                
                            client.send(f"Stream: {selected_stream}\n".encode())
                            client.send(f"Source: {settings['source']}\n".encode())
                            client.send(f"Resolution: {resolution}\n".encode())
                            client.send(f"JPEG Quality: {settings['jpeg_quality']}\n".encode())
                            client.send(f"Scale Factor: {settings['scale_factor']}\n".encode())
                            client.send(f"Pi Cam Preset: {settings['picam_preset']}\n".encode())
                            client.send(f"Frames: {stats['frames_captured']}\n".encode())
                            client.send(f"Clients: {stats['clients_connected']}\n> ".encode())
                        else:
                            client.send(f"ERROR: Stream '{selected_stream}' not found\n> ".encode())
                            
                # Help
                elif command == 'help':
                    client.send(b"\nVideo Multiplexer Control Commands\n")
                    client.send(b"===================================\n\n")
                    client.send(b"Stream Management:\n")
                    client.send(b"  streams              - List all streams\n")
                    client.send(b"  select <stream_id>   - Select stream to control\n\n")
                    client.send(b"Source Selection:\n")
                    for src in get_available_sources():
                        client.send(f"  {src:<20} - Switch to {src}\n".encode())
                    client.send(b"\nSettings:\n")
                    client.send(b"  quality <1-100>      - Set JPEG compression\n")
                    client.send(b"  scale <0.25-2.0>     - Scale Kinect output\n")
                    client.send(f"  picam_res <preset>   - Pi camera: {list(PICAM_PRESETS.keys())}\n".encode())
                    client.send(b"\nInfo:\n")
                    client.send(b"  status               - Show selected stream status\n")
                    client.send(b"  status all           - Show all streams status\n")
                    client.send(b"  help                 - This help\n")
                    client.send(b"  quit                 - Disconnect\n")
                    client.send(b"\n> ")
                    
                # Quit
                elif command in ['quit', 'exit', 'q']:
                    client.send(b"Goodbye!\n")
                    break
                    
                else:
                    client.send(f"Unknown command: {cmd}. Type 'help' for commands.\n> ".encode())
                    
        except Exception as e:
            if self.debug:
                print(f"Control client error: {e}")
        finally:
            try:
                client.close()
            except:
                pass
                
    def stop(self):
        """Stop the control server."""
        self.running = False
        if self.server:
            try:
                self.server.close()
            except:
                pass
            self.server = None


def create_control_server(manager: 'StreamManager', port: int, 
                          debug: bool = False) -> ControlServer:
    """Create a TCP control server.
    
    Args:
        manager: The StreamManager instance
        port: Port to listen on
        debug: Enable debug logging
        
    Returns:
        Configured ControlServer (not yet started)
    """
    return ControlServer(manager, port, debug)
