"""
Stream Manager - coordinates multiple video streams.

Handles frame capture and distribution to multiple independent streams,
each with their own source configuration.
"""

import threading
import time
from typing import Dict, Optional, Set

from .config import (
    CV2_AVAILABLE,
    KINECT_SOURCES,
    KINECT_AVAILABLE,
    FRAME_INTERVAL,
    PICAM_PRESETS,
    get_available_sources,
)
from .state import StreamState, GlobalState, global_state
from .sources.kinect import get_kinect
from .sources.picam import get_picam

if CV2_AVAILABLE:
    import cv2


class StreamManager:
    """Manages multiple video streams with shared capture resources.
    
    Each stream can independently select its video source, but capture
    resources (Kinect, Pi Camera) are shared efficiently.
    
    Example:
        manager = StreamManager()
        manager.create_stream('main', initial_source='kinect_rgb')
        manager.create_stream('secondary', initial_source='picam')
        manager.start()
    """
    
    def __init__(self, global_state_instance: Optional[GlobalState] = None):
        """Initialize the stream manager.
        
        Args:
            global_state_instance: Optional custom GlobalState instance.
                                   Uses the module global if not provided.
        """
        self.state = global_state_instance or global_state
        self.kinect = get_kinect()
        self.picam = get_picam()
        
        self._capture_thread: Optional[threading.Thread] = None
        self._running = False
        
        # Track which sources are actively needed
        self._active_sources: Set[str] = set()
        self._source_lock = threading.Lock()
        
    def create_stream(self, stream_id: str, initial_source: Optional[str] = None) -> StreamState:
        """Create a new video stream.
        
        Args:
            stream_id: Unique identifier for the stream (e.g., 'main', 'secondary')
            initial_source: Initial video source (defaults to best available)
            
        Returns:
            The created StreamState
        """
        if initial_source is None:
            initial_source = 'kinect_rgb' if KINECT_AVAILABLE else 'picam'
            
        # Validate source
        available = get_available_sources()
        if initial_source not in available:
            print(f"Warning: Requested source '{initial_source}' unavailable, using 'picam'")
            initial_source = 'picam'
            
        return self.state.create_stream(stream_id, initial_source)
        
    def get_stream(self, stream_id: str) -> Optional[StreamState]:
        """Get a stream by ID."""
        return self.state.get_stream(stream_id)
        
    def list_streams(self) -> list[str]:
        """List all stream IDs."""
        return self.state.list_streams()
        
    def switch_source(self, stream_id: str, source: str) -> tuple[bool, str]:
        """Switch a stream's video source.
        
        Args:
            stream_id: The stream to modify
            source: The new source ('kinect_rgb', 'kinect_ir', 'kinect_depth', 'picam')
            
        Returns:
            Tuple of (success, message)
        """
        stream = self.state.get_stream(stream_id)
        if stream is None:
            return False, f"Stream '{stream_id}' not found"
            
        available = get_available_sources()
        if source not in available:
            if source in KINECT_SOURCES:
                return False, f"Kinect unavailable. Available sources: {available}"
            return False, f"Unknown source '{source}'. Available: {available}"
            
        old_source = stream.set_source(source)
        return True, f"Switched {stream_id} from {old_source} to {source}"
        
    def start(self) -> None:
        """Start the capture thread."""
        if self._running:
            return
            
        self._running = True
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()
        
    def stop(self) -> None:
        """Stop the capture thread and release resources."""
        self._running = False
        self.state.shutdown()
        
        if self._capture_thread:
            self._capture_thread.join(timeout=2.0)
            self._capture_thread = None
            
        self.kinect.stop()
        self.picam.stop()
        
    def _get_active_sources(self) -> Dict[str, list[StreamState]]:
        """Get mapping of sources to streams that need them."""
        source_to_streams: Dict[str, list[StreamState]] = {}
        
        for stream_id in self.state.list_streams():
            stream = self.state.get_stream(stream_id)
            if stream:
                source = stream.current_source
                if source not in source_to_streams:
                    source_to_streams[source] = []
                source_to_streams[source].append(stream)
                
        return source_to_streams
        
    def _capture_loop(self) -> None:
        """Main capture loop - captures frames and distributes to streams."""
        last_picam_preset: Optional[str] = None
        picam_running = False
        
        while self._running and self.state.running:
            try:
                source_to_streams = self._get_active_sources()
                
                # Manage Pi camera lifecycle
                picam_needed = 'picam' in source_to_streams
                if picam_needed:
                    # Get the preset from the first stream using picam
                    preset = source_to_streams['picam'][0].picam_preset
                    if not picam_running or preset != last_picam_preset:
                        self.picam.start(preset)
                        last_picam_preset = preset
                        picam_running = True
                elif picam_running:
                    self.picam.stop()
                    picam_running = False
                    last_picam_preset = None
                    
                # Capture and distribute frames for each active source
                for source, streams in source_to_streams.items():
                    jpeg_bytes = self._capture_source(source, streams)
                    if jpeg_bytes:
                        for stream in streams:
                            stream.set_frame(jpeg_bytes)
                            
                time.sleep(FRAME_INTERVAL)
                
            except Exception as e:
                if self.state.debug:
                    print(f"Capture loop error: {e}")
                time.sleep(0.1)
                
        # Cleanup
        self.kinect.stop()
        self.picam.stop()
        
    def _capture_source(self, source: str, streams: list[StreamState]) -> Optional[bytes]:
        """Capture a frame from the specified source.
        
        Args:
            source: The source to capture from
            streams: List of streams using this source (for settings)
            
        Returns:
            JPEG bytes or None
        """
        if not CV2_AVAILABLE and source != 'picam':
            return None
            
        # Use settings from first stream (they may differ but we pick one)
        stream = streams[0]
        quality = stream.jpeg_quality
        scale = stream.scale_factor
        
        if source == 'kinect_rgb':
            frame = self.kinect.get_frame('rgb', scale)
            if frame is not None:
                _, jpeg = cv2.imencode('.jpg', frame, 
                    [cv2.IMWRITE_JPEG_QUALITY, quality])
                return jpeg.tobytes()
                
        elif source == 'kinect_ir':
            frame = self.kinect.get_frame('ir', scale)
            if frame is not None:
                _, jpeg = cv2.imencode('.jpg', frame,
                    [cv2.IMWRITE_JPEG_QUALITY, quality])
                return jpeg.tobytes()
                
        elif source == 'kinect_depth':
            frame = self.kinect.get_frame('depth', scale)
            if frame is not None:
                _, jpeg = cv2.imencode('.jpg', frame,
                    [cv2.IMWRITE_JPEG_QUALITY, quality])
                return jpeg.tobytes()
                
        elif source == 'picam':
            return self.picam.get_frame()
            
        return None
        
    def get_status(self) -> Dict:
        """Get status information for all streams."""
        streams_info = {}
        for stream_id in self.state.list_streams():
            stream = self.state.get_stream(stream_id)
            if stream:
                settings = stream.get_settings()
                stats = stream.get_stats()
                
                # Calculate resolution
                if settings['source'] == 'picam':
                    preset = PICAM_PRESETS.get(settings['picam_preset'], PICAM_PRESETS['high'])
                    resolution = f"{preset['width']}x{preset['height']}"
                else:
                    from .config import KINECT_WIDTH, KINECT_HEIGHT
                    w = int(KINECT_WIDTH * settings['scale_factor'])
                    h = int(KINECT_HEIGHT * settings['scale_factor'])
                    resolution = f"{w}x{h}"
                    
                streams_info[stream_id] = {
                    **settings,
                    **stats,
                    'resolution': resolution,
                }
                
        return {
            'running': self._running,
            'kinect_available': KINECT_AVAILABLE,
            'available_sources': get_available_sources(),
            'streams': streams_info,
        }
