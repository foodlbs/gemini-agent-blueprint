"""Local video post-processing using ``ffmpeg-python``.

The Video Asset Agent calls ``convert_to_gif`` to produce the inline embed
for Medium and ``extract_first_frame`` to produce the JPEG poster used as
the GitHub repo's preview image. Both shell out to the local ffmpeg binary.
"""

import logging
import os
import tempfile

import ffmpeg

logger = logging.getLogger(__name__)

DEFAULT_GIF_FPS = 10
DEFAULT_GIF_MAX_WIDTH = 720


def convert_to_gif(
    mp4_bytes: bytes,
    fps: int = DEFAULT_GIF_FPS,
    max_width: int = DEFAULT_GIF_MAX_WIDTH,
) -> bytes:
    """Convert MP4 bytes to a Medium-friendly GIF.

    Output is a single GIF at the requested fps and width (height scales
    proportionally). The default 720px / 10fps keeps Medium-friendly file
    size while staying watchable.

    Args:
        mp4_bytes: Raw MP4 bytes from Veo.
        fps: Target frames per second.
        max_width: Max width in pixels; height is auto-scaled.

    Returns:
        Bytes of the encoded GIF.
    """
    in_path, out_path = _temp_pair(".mp4", ".gif")
    try:
        with open(in_path, "wb") as f:
            f.write(mp4_bytes)
        (
            ffmpeg
            .input(in_path)
            .filter("fps", fps=fps)
            .filter("scale", max_width, -1)
            .output(out_path)
            .overwrite_output()
            .run(quiet=True)
        )
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        _cleanup(in_path, out_path)


def extract_first_frame(mp4_bytes: bytes) -> bytes:
    """Extract the first frame of an MP4 as a JPEG.

    Used as the video's poster image (e.g., the GitHub repo's
    ``assets/tutorial-poster.jpg``).

    Args:
        mp4_bytes: Raw MP4 bytes from Veo.

    Returns:
        Bytes of the JPEG-encoded frame.
    """
    in_path, out_path = _temp_pair(".mp4", ".jpg")
    try:
        with open(in_path, "wb") as f:
            f.write(mp4_bytes)
        (
            ffmpeg
            .input(in_path)
            .output(out_path, vframes=1, format="image2", vcodec="mjpeg")
            .overwrite_output()
            .run(quiet=True)
        )
        with open(out_path, "rb") as f:
            return f.read()
    finally:
        _cleanup(in_path, out_path)


def _temp_pair(suffix_in: str, suffix_out: str) -> tuple[str, str]:
    """Allocate two temp file paths. Caller is responsible for cleanup."""
    in_fd, in_path = tempfile.mkstemp(suffix=suffix_in)
    os.close(in_fd)
    out_fd, out_path = tempfile.mkstemp(suffix=suffix_out)
    os.close(out_fd)
    return in_path, out_path


def _cleanup(*paths: str) -> None:
    for p in paths:
        try:
            if os.path.exists(p):
                os.unlink(p)
        except OSError as e:
            logger.warning("temp cleanup failed for %s: %s", p, e)
