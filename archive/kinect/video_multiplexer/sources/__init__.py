"""
Video source capture modules.
"""

from .base import VideoSource
from .kinect import KinectCapture
from .picam import PiCameraCapture

__all__ = ['VideoSource', 'KinectCapture', 'PiCameraCapture']
