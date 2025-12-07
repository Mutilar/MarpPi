"""
TCP raw video streaming server.

Provides a secondary stream as raw JPEG frames over TCP for lower latency
or programmatic consumption.
"""

import socket
import struct
import threading
from typing import TYPE_CHECKING, Optional

from ..state import global_state

if TYPE_CHECKING:
    from ..manager import StreamManager


class TCPStreamHandler:
    """Handles a single TCP client connection for raw video streaming.
    
    Protocol:
        Each frame is sent as:
        - 4 bytes: Frame length (big-endian uint32)
        - N bytes: JPEG data
        
        Client can send single-byte commands:
        - 0x00: Keepalive/ping
        - 0x01: Request status (server responds with JSON)
    """
    
    def __init__(self, client: socket.socket, manager: 'StreamManager', 
                 stream_id: str, debug: bool = False):
        self.client = client
        self.manager = manager
        self.stream_id = stream_id
        self.debug = debug
        self.running = True
        
    def handle(self):
        """Handle the client connection."""
        stream = self.manager.get_stream(self.stream_id)
        if stream is None:
            self.client.sendall(b'ERROR: Stream not found\n')
            self.client.close()
            return
            
        stream.increment_clients()
        last_frame_id = 0
        
        # Set socket to non-blocking for checking commands
        self.client.setblocking(False)
        
        try:
            while self.running and global_state.running:
                # Check for incoming commands (non-blocking)
                try:
                    cmd = self.client.recv(1)
                    if cmd == b'\x00':
                        # Keepalive - respond with single byte
                        self.client.sendall(b'\x00')
                    elif cmd == b'\x01':
                        # Status request
                        import json
                        status = self.manager.get_status()
                        status_bytes = json.dumps(status).encode()
                        self.client.sendall(struct.pack('>I', len(status_bytes)))
                        self.client.sendall(status_bytes)
                    elif cmd == b'':
                        # Client disconnected
                        break
                except BlockingIOError:
                    pass  # No command pending
                except:
                    break
                    
                # Get and send frame
                frame, last_frame_id = stream.get_frame(last_frame_id, timeout=0.1)
                
                if frame is None:
                    continue
                    
                try:
                    # Send frame length + data
                    self.client.sendall(struct.pack('>I', len(frame)))
                    self.client.sendall(frame)
                    stream.increment_frames_sent()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
                    
        except Exception as e:
            if self.debug:
                print(f"TCP client error: {e}")
        finally:
            stream.decrement_clients()
            try:
                self.client.close()
            except:
                pass
                
    def stop(self):
        """Signal the handler to stop."""
        self.running = False


class TCPStreamServer:
    """TCP server for raw video streaming.
    
    Each connected client receives a continuous stream of JPEG frames
    with a simple length-prefixed protocol.
    """
    
    def __init__(self, manager: 'StreamManager', stream_id: str, port: int,
                 debug: bool = False):
        self.manager = manager
        self.stream_id = stream_id
        self.port = port
        self.debug = debug
        self.running = False
        self.server: Optional[socket.socket] = None
        self.handlers: list[TCPStreamHandler] = []
        self._accept_thread: Optional[threading.Thread] = None
        
    def start(self):
        """Start the TCP server."""
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
        
        print(f"TCP stream server started on port {self.port} (stream: {self.stream_id})")
        
    def _accept_loop(self):
        """Accept incoming connections."""
        while self.running and global_state.running:
            try:
                client, addr = self.server.accept()
                if self.debug:
                    print(f"TCP stream client connected from {addr}")
                    
                handler = TCPStreamHandler(client, self.manager, self.stream_id, self.debug)
                self.handlers.append(handler)
                
                thread = threading.Thread(target=handler.handle, daemon=True)
                thread.start()
                
            except socket.timeout:
                continue
            except Exception as e:
                if self.running and self.debug:
                    print(f"TCP accept error: {e}")
                    
    def stop(self):
        """Stop the TCP server."""
        self.running = False
        
        # Stop all handlers
        for handler in self.handlers:
            handler.stop()
        self.handlers.clear()
        
        if self.server:
            try:
                self.server.close()
            except:
                pass
            self.server = None


def create_tcp_stream_server(manager: 'StreamManager', stream_id: str, port: int,
                             debug: bool = False) -> TCPStreamServer:
    """Create a TCP raw video streaming server.
    
    Args:
        manager: The StreamManager instance
        stream_id: Which stream this server serves
        port: Port to listen on
        debug: Enable debug logging
        
    Returns:
        Configured TCPStreamServer (not yet started)
    """
    return TCPStreamServer(manager, stream_id, port, debug)
