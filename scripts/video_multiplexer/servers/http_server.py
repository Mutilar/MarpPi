"""
HTTP MJPEG streaming server with web viewer.
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from typing import TYPE_CHECKING

from ..config import PICAM_PRESETS, KINECT_WIDTH, KINECT_HEIGHT, KINECT_SOURCES, get_available_sources
from ..state import global_state
from ..templates import render_template

if TYPE_CHECKING:
    from ..manager import StreamManager


class MJPEGStreamHandler(BaseHTTPRequestHandler):
    """HTTP handler for MJPEG streaming and web viewer."""
    
    # Set by factory function
    manager: 'StreamManager' = None
    stream_id: str = 'main'
    debug: bool = False
    
    def log_message(self, format, *args):
        if self.debug:
            print(f"HTTP: {args[0]}")
            
    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.send_viewer_page()
        elif self.path == '/dual' or self.path == '/dual.html':
            self.send_dual_viewer_page()
        elif self.path == '/stream.mjpg' or self.path == '/stream':
            self.send_mjpeg_stream()
        elif self.path.startswith('/stream/'):
            # /stream/main or /stream/secondary
            stream_name = self.path.split('/stream/')[-1].split('?')[0].rstrip('/')
            self.send_mjpeg_stream(stream_name)
        elif self.path == '/status':
            self.send_status()
        elif self.path.startswith('/switch'):
            self.handle_switch()
        elif self.path == '/favicon.ico':
            self.send_error(404)
        else:
            self.send_error(404)
            
    def do_POST(self):
        if self.path.startswith('/switch'):
            self.handle_switch()
        else:
            self.send_error(404)
            
    def send_viewer_page(self):
        """Send HTML page with embedded MJPEG viewer and multi-stream controls."""
        streams = self.manager.list_streams()
        stream_buttons = '\n'.join([
            f'<button onclick="selectStream(\'{s}\')" id="stream-btn-{s}" '
            f'class="{"active" if s == self.stream_id else ""}">{s.title()}</button>'
            for s in streams
        ])
        
        html = render_template('viewer.html',
                               stream_id=self.stream_id,
                               stream_buttons=stream_buttons)
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', len(html))
        self.end_headers()
        self.wfile.write(html.encode())

    def send_dual_viewer_page(self):
        """Send HTML page with both streams side-by-side."""
        html = render_template('dual_viewer.html')
        
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', len(html))
        self.end_headers()
        self.wfile.write(html.encode())
        
    def send_mjpeg_stream(self, stream_id: str = None):
        """Send continuous MJPEG stream."""
        if stream_id is None:
            stream_id = self.stream_id
        stream = self.manager.get_stream(stream_id)
        if stream is None:
            self.send_error(404, f"Stream '{stream_id}' not found")
            return
            
        self.send_response(200)
        self.send_header('Content-Type', 
                         'multipart/x-mixed-replace; boundary=--jpgboundary')
        self.send_header('Cache-Control', 'no-cache, private')
        self.send_header('Pragma', 'no-cache')
        self.end_headers()
        
        stream.increment_clients()
        last_frame_id = 0
            
        try:
            while global_state.running:
                frame, last_frame_id = stream.get_frame(last_frame_id, timeout=1.0)
                
                if frame is None:
                    continue
                    
                try:
                    self.wfile.write(b'--jpgboundary\r\n')
                    self.wfile.write(b'Content-Type: image/jpeg\r\n')
                    self.wfile.write(f'Content-Length: {len(frame)}\r\n\r\n'.encode())
                    self.wfile.write(frame)
                    self.wfile.write(b'\r\n')
                    self.wfile.flush()
                    
                    stream.increment_frames_sent()
                        
                except (BrokenPipeError, ConnectionResetError):
                    break
                
        finally:
            stream.decrement_clients()
                
    def send_status(self):
        """Send JSON status for all streams."""
        status = self.manager.get_status()
        body = json.dumps(status).encode()
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)
        
    def handle_switch(self):
        """Handle source/settings switch."""
        if '?' not in self.path:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'ERROR: Missing parameters\n')
            return
            
        query = self.path.split('?')[1]
        params = dict(p.split('=') for p in query.split('&') if '=' in p)
        
        # Determine which stream to modify
        target_stream_id = params.get('stream', self.stream_id)
        stream = self.manager.get_stream(target_stream_id)
        
        if stream is None:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(f'ERROR: Stream "{target_stream_id}" not found\n'.encode())
            return
            
        response_parts = []
        
        # Handle source switch
        source = params.get('source', '')
        if source:
            success, msg = self.manager.switch_source(target_stream_id, source)
            if not success:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f'ERROR: {msg}\n'.encode())
                return
            response_parts.append(f"source={source}")
        
        # Handle quality
        quality = params.get('quality', '')
        if quality:
            try:
                q = int(quality)
                if 1 <= q <= 100:
                    stream.update_settings(jpeg_quality=q)
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
                    stream.update_settings(scale_factor=s)
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
                stream.update_settings(picam_preset=picam_res)
                response_parts.append(f"picam_res={picam_res}")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f'ERROR: picam_res must be: {list(PICAM_PRESETS.keys())}\n'.encode())
                return
        
        if response_parts:
            self.send_response(200)
            self.end_headers()
            self.wfile.write(f'OK: {", ".join(response_parts)} (stream: {target_stream_id})\n'.encode())
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'ERROR: No valid parameters. Use: source, quality, scale, picam_res\n')


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Threaded HTTP server for handling multiple clients."""
    daemon_threads = True
    allow_reuse_address = True


def create_http_server(manager: 'StreamManager', stream_id: str, port: int, 
                       debug: bool = False) -> ThreadedHTTPServer:
    """Create an HTTP MJPEG streaming server for a specific stream.
    
    Args:
        manager: The StreamManager instance
        stream_id: Which stream this server serves
        port: Port to listen on
        debug: Enable debug logging
        
    Returns:
        Configured ThreadedHTTPServer (not yet started)
    """
    # Create a custom handler class with the manager bound
    class BoundHandler(MJPEGStreamHandler):
        pass
        
    BoundHandler.manager = manager
    BoundHandler.stream_id = stream_id
    BoundHandler.debug = debug
    
    server = ThreadedHTTPServer(('0.0.0.0', port), BoundHandler)
    return server
