"""
Kinect video capture using libfreenect.
"""

import threading
from typing import Optional
import numpy as np

from ..config import (
    FREENECT_AVAILABLE,
    CV2_AVAILABLE,
    KINECT_WIDTH,
    KINECT_HEIGHT,
    update_kinect_availability,
    KINECT_AVAILABLE,
)
from .base import VideoSource

if FREENECT_AVAILABLE:
    import freenect
    
if CV2_AVAILABLE:
    import cv2


class KinectCapture(VideoSource):
    """Manages Kinect video capture with mode switching.
    
    Note: The freenect sync API only supports RESOLUTION_MEDIUM (640x480).
    Higher resolutions require using the async API which is more complex.
    We support output scaling via OpenCV for flexibility.
    
    Supported modes:
      - 'rgb': Color camera
      - 'ir': Infrared camera
      - 'depth': Depth camera with colormap
    """
    
    _instance: Optional['KinectCapture'] = None
    _lock = threading.Lock()
    
    def __new__(cls):
        """Singleton pattern - only one Kinect instance allowed."""
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
            
        self._initialized = True
        self.lock = threading.Lock()
        self.consecutive_failures = 0
        self.max_failures = 5
        self._available = False
        self.debug = False
        
        # Check availability on init
        self.check_availability()
        
    def check_availability(self) -> bool:
        """Test if Kinect is actually connected and working."""
        if not FREENECT_AVAILABLE or not CV2_AVAILABLE:
            self._available = False
            update_kinect_availability(False)
            return False
            
        try:
            data = freenect.sync_get_video(0, freenect.VIDEO_RGB)
            if data is not None:
                self._available = True
                update_kinect_availability(True)
                self.consecutive_failures = 0
                return True
        except Exception as e:
            if self.debug:
                print(f"Kinect availability check failed: {e}")
        
        self._available = False
        update_kinect_availability(False)
        return False
        
    def _mark_unavailable(self) -> None:
        """Mark Kinect as unavailable."""
        self._available = False
        update_kinect_availability(False)
        
    def is_available(self) -> bool:
        """Check if Kinect is currently available."""
        return self._available and FREENECT_AVAILABLE and CV2_AVAILABLE
        
    def get_frame(self, mode: str = 'rgb', scale_factor: float = 1.0) -> Optional[np.ndarray]:
        """Get a frame from Kinect in the specified mode.
        
        Args:
            mode: 'rgb', 'ir', or 'depth'
            scale_factor: Output scaling (1.0 = native 640x480)
            
        Returns:
            numpy array (BGR format ready for cv2) or None
        """
        if not self.is_available():
            return None
            
        try:
            with self.lock:
                if mode == 'rgb':
                    data = freenect.sync_get_video(0, freenect.VIDEO_RGB)
                    if data is None:
                        self._handle_failure()
                        return None
                    frame = data[0]
                    frame = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
                    
                elif mode == 'ir':
                    data = freenect.sync_get_video(0, freenect.VIDEO_IR_8BIT)
                    if data is None:
                        self._handle_failure()
                        return None
                    frame = data[0]
                    frame = cv2.cvtColor(frame, cv2.COLOR_GRAY2BGR)
                    
                elif mode == 'depth':
                    data = freenect.sync_get_depth()
                    if data is None:
                        self._handle_failure()
                        return None
                    frame = data[0]
                    np.clip(frame, 0, 2047, out=frame)
                    frame = (frame >> 3).astype(np.uint8)
                    frame = cv2.applyColorMap(frame, cv2.COLORMAP_JET)
                else:
                    return None
                
                # Success - reset failure counter
                self.consecutive_failures = 0
                    
                # Apply scaling if needed
                if scale_factor != 1.0 and frame is not None:
                    new_width = int(KINECT_WIDTH * scale_factor)
                    new_height = int(KINECT_HEIGHT * scale_factor)
                    frame = cv2.resize(frame, (new_width, new_height), 
                                       interpolation=cv2.INTER_LINEAR)
                
                return frame
                    
        except Exception as e:
            if self.debug:
                print(f"Kinect capture error ({mode}): {e}")
            self._handle_failure()
            return None
            
    def _handle_failure(self) -> None:
        """Handle a capture failure."""
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_failures:
            self._mark_unavailable()
            
    def stop(self) -> None:
        """Clean up Kinect resources."""
        if FREENECT_AVAILABLE:
            try:
                freenect.sync_stop()
            except:
                pass


# Module-level singleton accessor
_kinect_instance: Optional[KinectCapture] = None

def get_kinect() -> KinectCapture:
    """Get the singleton Kinect capture instance."""
    global _kinect_instance
    if _kinect_instance is None:
        _kinect_instance = KinectCapture()
    return _kinect_instance
