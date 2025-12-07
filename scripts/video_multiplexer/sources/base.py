"""
Base class for video sources.
"""

from abc import ABC, abstractmethod
from typing import Optional
import numpy as np


class VideoSource(ABC):
    """Abstract base class for video capture sources."""
    
    @abstractmethod
    def get_frame(self, **kwargs) -> Optional[np.ndarray]:
        """Capture and return a frame.
        
        Returns:
            numpy array in BGR format (for OpenCV) or None if unavailable
        """
        pass
        
    @abstractmethod
    def is_available(self) -> bool:
        """Check if this source is currently available."""
        pass
        
    @abstractmethod
    def stop(self) -> None:
        """Release any resources held by this source."""
        pass
        
    def start(self, **kwargs) -> bool:
        """Start the capture source (if needed).
        
        Returns:
            True if successfully started
        """
        return True
