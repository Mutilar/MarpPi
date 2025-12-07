"""
Server orchestration and startup.
"""

import signal
import threading
from typing import TYPE_CHECKING, List, Optional

from .http_server import create_http_server, ThreadedHTTPServer
from .tcp_server import create_tcp_stream_server, TCPStreamServer
from .control_server import create_control_server, ControlServer
from ..state import global_state

if TYPE_CHECKING:
    from ..manager import StreamManager


class ServerOrchestrator:
    """Orchestrates multiple servers for the video multiplexer."""
    
    def __init__(self, manager: 'StreamManager'):
        self.manager = manager
        self.http_servers: List[ThreadedHTTPServer] = []
        self.tcp_servers: List[TCPStreamServer] = []
        self.control_server: Optional[ControlServer] = None
        self._server_threads: List[threading.Thread] = []
        
    def add_http_stream(self, stream_id: str, port: int, debug: bool = False):
        """Add an HTTP MJPEG stream server."""
        server = create_http_server(self.manager, stream_id, port, debug)
        self.http_servers.append(server)
        return server
        
    def add_tcp_stream(self, stream_id: str, port: int, debug: bool = False):
        """Add a TCP raw stream server."""
        server = create_tcp_stream_server(self.manager, stream_id, port, debug)
        self.tcp_servers.append(server)
        return server
        
    def set_control_server(self, port: int, debug: bool = False):
        """Set up the control server."""
        self.control_server = create_control_server(self.manager, port, debug)
        return self.control_server
        
    def start_all(self):
        """Start all configured servers."""
        # Start TCP stream servers
        for server in self.tcp_servers:
            server.start()
            
        # Start control server
        if self.control_server:
            self.control_server.start()
            
        # Start HTTP servers (each in its own thread)
        for server in self.http_servers:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self._server_threads.append(thread)
            print(f"HTTP server started on port {server.server_address[1]}")
            
    def stop_all(self):
        """Stop all servers."""
        # Signal global shutdown
        global_state.shutdown()
        
        # Stop HTTP servers
        for server in self.http_servers:
            server.shutdown()
            
        # Stop TCP stream servers
        for server in self.tcp_servers:
            server.stop()
            
        # Stop control server
        if self.control_server:
            self.control_server.stop()
            
        # Wait for threads
        for thread in self._server_threads:
            thread.join(timeout=2.0)
            
    def run_forever(self):
        """Run all servers until interrupted."""
        # Set up signal handlers
        def signal_handler(sig, frame):
            print("\nShutting down...")
            self.stop_all()
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        self.start_all()
        
        # Block on the first HTTP server (or just wait)
        try:
            if self.http_servers:
                # The HTTP servers are already running in threads,
                # so we just wait for the shutdown signal
                while global_state.running:
                    import time
                    time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop_all()


def start_servers(manager: 'StreamManager', 
                  main_http_port: int = 5600,
                  secondary_tcp_port: int = 5601,
                  control_port: int = 5603,
                  debug: bool = False) -> ServerOrchestrator:
    """Convenience function to start all servers with default configuration.
    
    Args:
        manager: The StreamManager instance
        main_http_port: Port for main HTTP MJPEG stream
        secondary_tcp_port: Port for secondary TCP raw stream
        control_port: Port for control server
        debug: Enable debug logging
        
    Returns:
        ServerOrchestrator instance (already running)
    """
    orchestrator = ServerOrchestrator(manager)
    
    # Set up HTTP server for main stream
    orchestrator.add_http_stream('main', main_http_port, debug)
    
    # Set up TCP server for secondary stream
    orchestrator.add_tcp_stream('secondary', secondary_tcp_port, debug)
    
    # Set up control server
    orchestrator.set_control_server(control_port, debug)
    
    return orchestrator
