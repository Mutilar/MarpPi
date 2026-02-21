"""
Raspberry Pi Camera capture via subprocess.
"""

import subprocess
import threading
from typing import Optional

from ..config import PICAM_PRESETS, CV2_AVAILABLE
from .base import VideoSource

if CV2_AVAILABLE:
    import cv2


class PiCameraCapture(VideoSource):
    """Manages Pi Camera capture via rpicam-vid subprocess.
    
    Unlike the Kinect (which is a singleton), multiple PiCameraCapture
    instances can exist but only one can be actively capturing at a time
    due to hardware limitations.
    """
    
    # Class-level lock for hardware access
    _hardware_lock = threading.Lock()
    _active_instance: Optional['PiCameraCapture'] = None
    
    def __init__(self):
        self.process: Optional[subprocess.Popen] = None
        self.lock = threading.Lock()
        self.frame_buffer: Optional[bytes] = None
        self.capture_thread: Optional[threading.Thread] = None
        self.running = False
        self.current_preset: Optional[str] = None
        self.debug = False
        self._available_command: Optional[str] = None
        
        # Check for available camera command
        self._detect_camera_command()
        
    def _detect_camera_command(self) -> None:
        """Detect which camera command is available."""
        for candidate in ['rpicam-vid', 'libcamera-vid']:
            try:
                subprocess.run([candidate, '--help'], 
                               capture_output=True, timeout=2)
                self._available_command = candidate
                break
            except:
                continue
                
    def is_available(self) -> bool:
        """Check if Pi camera is available."""
        return self._available_command is not None
        
    def start(self, preset: str = 'high') -> bool:
        """Start the Pi camera capture subprocess.
        
        Args:
            preset: Resolution preset ('low', 'medium', 'high', 'full')
            
        Returns:
            True if successfully started
        """
        with self._hardware_lock:
            # Stop any other active instance
            if PiCameraCapture._active_instance is not None and \
               PiCameraCapture._active_instance is not self:
                PiCameraCapture._active_instance._stop_internal()
                
            with self.lock:
                # Check if we need to restart with new settings
                if self.process is not None:
                    if self.current_preset == preset:
                        return True
                    self._stop_internal()
                    
                if self._available_command is None:
                    print("Warning: No Pi camera command available")
                    return False
                    
                settings = PICAM_PRESETS.get(preset, PICAM_PRESETS['high'])
                
                try:
                    self.process = subprocess.Popen([
                        self._available_command,
                        '-t', '0',
                        '-n',
                        '--width', str(settings['width']),
                        '--height', str(settings['height']),
                        '--framerate', str(settings['fps']),
                        '--codec', 'mjpeg',
                        '-o', '-'
                    ], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
                    
                    self.running = True
                    self.current_preset = preset
                    self.capture_thread = threading.Thread(target=self._capture_loop)
                    self.capture_thread.daemon = True
                    self.capture_thread.start()
                    
                    PiCameraCapture._active_instance = self
                    
                    print(f"Started Pi camera: {self._available_command} @ "
                          f"{settings['width']}x{settings['height']} {settings['fps']}fps ({preset})")
                    return True
                    
                except Exception as e:
                    print(f"Failed to start Pi camera: {e}")
                    return False
                
    def _capture_loop(self) -> None:
        """Read MJPEG frames from subprocess stdout."""
        buffer = b''
        while self.running and self.process:
            try:
                chunk = self.process.stdout.read(4096)
                if not chunk:
                    break
                buffer += chunk
                
                # Find JPEG boundaries (SOI and EOI markers)
                while True:
                    soi = buffer.find(b'\xff\xd8')
                    if soi == -1:
                        buffer = b''
                        break
                        
                    eoi = buffer.find(b'\xff\xd9', soi)
                    if eoi == -1:
                        buffer = buffer[soi:]
                        break
                        
                    # Extract complete JPEG
                    jpeg_data = buffer[soi:eoi+2]
                    buffer = buffer[eoi+2:]
                    
                    with self.lock:
                        self.frame_buffer = jpeg_data
                        
            except Exception as e:
                if self.debug:
                    print(f"Pi camera read error: {e}")
                break
                
    def get_frame(self, **kwargs) -> Optional[bytes]:
        """Get the latest JPEG frame from Pi camera.
        
        Note: Returns raw JPEG bytes, not a numpy array.
        This is more efficient as Pi camera outputs MJPEG directly.
        
        Returns:
            JPEG bytes or None
        """
        with self.lock:
            return self.frame_buffer
    
    def _stop_internal(self) -> None:
        """Internal stop without locks (caller must hold lock)."""
        self.running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except:
                self.process.kill()
            self.process = None
        self.frame_buffer = None
        self.current_preset = None
        
        if PiCameraCapture._active_instance is self:
            PiCameraCapture._active_instance = None
            
    def stop(self) -> None:
        """Stop the Pi camera subprocess."""
        with self._hardware_lock:
            with self.lock:
                self._stop_internal()


# Module-level instance for shared use
_picam_instance: Optional[PiCameraCapture] = None

def get_picam() -> PiCameraCapture:
    """Get the shared Pi camera instance."""
    global _picam_instance
    if _picam_instance is None:
        _picam_instance = PiCameraCapture()
    return _picam_instance
