# Archived: Kinect Support

These files were archived on 2026-02-20 because the Xbox Kinect was removed
from the current robot build due to physical constraints.

## Contents

| Item | Description |
|------|-------------|
| `libfreenect/` | Vendored [OpenKinect/libfreenect](https://github.com/OpenKinect/libfreenect) submodule for Kinect RGB/depth/IR/motor/LED access |
| `video_multiplexer/` | Python package — multi-source MJPEG server with hot-swap between Kinect (RGB, IR, depth) and Pi Camera |
| `video_multiplexer.py` | Standalone version of the multiplexer (single-file, superseded by the package) |
| `video_client.py` | OpenCV-based viewer / TCP control client for the multiplexer |

## Restoring

If the Kinect is re-introduced in a future build:

1. Move `libfreenect/` back to `MarpPi/libfreenect/`
2. Move `video_multiplexer/` back to `MarpPi/scripts/video_multiplexer/`
3. Move `video_client.py` back to `MarpPi/scripts/video_client.py`
4. Re-add the libfreenect submodule reference and build steps to the main README
5. Update `start-video-stream.sh` to launch the multiplexer instead of the simple picam stream
