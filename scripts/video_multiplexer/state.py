"""
State management for video streams.

Supports multiple independent streams, each with their own source and settings.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any

from .config import (
    JPEG_QUALITY,
    DEFAULT_PICAM_PRESET,
    DEFAULT_SOURCE,
)


@dataclass
class StreamStats:
    """Statistics for a single stream."""
    frames_captured: int = 0
    frames_sent: int = 0
    clients_connected: int = 0
    source_switches: int = 0
    last_frame_time: float = 0


class StreamState:
    """State for a single video stream.
    
    Each stream has its own:
      - Current video source
      - Frame buffer
      - Quality/scale settings
      - Client notification system
      - Statistics
    """
    
    def __init__(self, stream_id: str, initial_source: Optional[str] = None):
        self.stream_id = stream_id
        self.lock = threading.Lock()
        self.frame_condition = threading.Condition(self.lock)
        
        # Stream source and frame
        self.current_source = initial_source or DEFAULT_SOURCE
        self.frame: Optional[bytes] = None
        self.frame_id: int = 0
        
        # Configurable settings
        self.jpeg_quality: int = JPEG_QUALITY
        self.scale_factor: float = 1.0
        self.picam_preset: str = DEFAULT_PICAM_PRESET
        
        # Statistics
        self.stats = StreamStats()
        
    def set_frame(self, jpeg_bytes: bytes) -> None:
        """Update the current frame and notify waiting clients."""
        with self.frame_condition:
            self.frame = jpeg_bytes
            self.frame_id += 1
            self.stats.frames_captured += 1
            self.stats.last_frame_time = time.time()
            self.frame_condition.notify_all()
            
    def get_frame(self, last_frame_id: int = 0, timeout: float = 1.0) -> tuple[Optional[bytes], int]:
        """Wait for and return the next frame.
        
        Args:
            last_frame_id: The last frame ID the client received
            timeout: Maximum time to wait for a new frame
            
        Returns:
            Tuple of (frame_bytes, frame_id) or (None, last_frame_id) on timeout
        """
        with self.frame_condition:
            # Wait for a new frame
            deadline = time.time() + timeout
            while self.frame_id == last_frame_id:
                remaining = deadline - time.time()
                if remaining <= 0:
                    return None, last_frame_id
                if not self.frame_condition.wait(timeout=remaining):
                    return None, last_frame_id
                    
            return self.frame, self.frame_id
            
    def set_source(self, source: str) -> str:
        """Set the video source for this stream.
        
        Returns:
            The previous source
        """
        with self.lock:
            old_source = self.current_source
            self.current_source = source
            self.stats.source_switches += 1
            return old_source
            
    def get_settings(self) -> Dict[str, Any]:
        """Get current stream settings."""
        with self.lock:
            return {
                'stream_id': self.stream_id,
                'source': self.current_source,
                'jpeg_quality': self.jpeg_quality,
                'scale_factor': self.scale_factor,
                'picam_preset': self.picam_preset,
            }
            
    def update_settings(self, **kwargs) -> None:
        """Update stream settings."""
        with self.lock:
            if 'jpeg_quality' in kwargs:
                self.jpeg_quality = max(1, min(100, int(kwargs['jpeg_quality'])))
            if 'scale_factor' in kwargs:
                self.scale_factor = max(0.25, min(2.0, float(kwargs['scale_factor'])))
            if 'picam_preset' in kwargs:
                self.picam_preset = kwargs['picam_preset']
                
    def increment_clients(self) -> int:
        """Increment connected client count."""
        with self.lock:
            self.stats.clients_connected += 1
            return self.stats.clients_connected
            
    def decrement_clients(self) -> int:
        """Decrement connected client count."""
        with self.lock:
            self.stats.clients_connected = max(0, self.stats.clients_connected - 1)
            return self.stats.clients_connected
            
    def increment_frames_sent(self) -> None:
        """Increment the frames sent counter."""
        with self.lock:
            self.stats.frames_sent += 1
            
    def get_stats(self) -> Dict[str, Any]:
        """Get stream statistics."""
        with self.lock:
            return {
                'frames_captured': self.stats.frames_captured,
                'frames_sent': self.stats.frames_sent,
                'clients_connected': self.stats.clients_connected,
                'source_switches': self.stats.source_switches,
                'last_frame_time': self.stats.last_frame_time,
            }


class GlobalState:
    """Global application state managing multiple streams."""
    
    def __init__(self):
        self.lock = threading.Lock()
        self.running = True
        self.debug = False
        self.streams: Dict[str, StreamState] = {}
        
    def create_stream(self, stream_id: str, initial_source: Optional[str] = None) -> StreamState:
        """Create a new stream with the given ID."""
        with self.lock:
            if stream_id in self.streams:
                raise ValueError(f"Stream '{stream_id}' already exists")
            stream = StreamState(stream_id, initial_source)
            self.streams[stream_id] = stream
            return stream
            
    def get_stream(self, stream_id: str) -> Optional[StreamState]:
        """Get a stream by ID."""
        with self.lock:
            return self.streams.get(stream_id)
            
    def list_streams(self) -> list[str]:
        """List all stream IDs."""
        with self.lock:
            return list(self.streams.keys())
            
    def remove_stream(self, stream_id: str) -> bool:
        """Remove a stream."""
        with self.lock:
            if stream_id in self.streams:
                del self.streams[stream_id]
                return True
            return False
            
    def shutdown(self) -> None:
        """Signal all threads to stop."""
        self.running = False
        # Wake up any waiting threads
        with self.lock:
            for stream in self.streams.values():
                with stream.frame_condition:
                    stream.frame_condition.notify_all()


# Global state instance
global_state = GlobalState()
