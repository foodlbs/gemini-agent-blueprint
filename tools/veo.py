"""Video generation via Vertex AI (Veo 3.1 Fast)."""

import logging
import os
import time
from typing import Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("VEO_MODEL", "veo-3.1-fast-generate-preview")
MAX_DURATION_SECONDS = 8  # DESIGN.md §7b: cap at 8s.
POLL_INTERVAL_SECONDS = 10
MAX_WAIT_SECONDS = 600  # 10 minutes — Veo Fast usually finishes in 1-3.

_client_singleton: Optional[genai.Client] = None


def _client() -> genai.Client:
    global _client_singleton
    if _client_singleton is None:
        project = _required_env("GOOGLE_CLOUD_PROJECT")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
        _client_singleton = genai.Client(
            vertexai=True, project=project, location=location
        )
    return _client_singleton


def reset_client(client: Optional[genai.Client] = None) -> None:
    """Test/dev helper: replace or clear the module-level GenAI client."""
    global _client_singleton
    _client_singleton = client


def generate_video(
    prompt: str,
    duration_seconds: int = 6,
    aspect_ratio: str = "16:9",
) -> bytes:
    """Generate one video and return its MP4 bytes.

    Calls Veo 3.1 Fast via Vertex AI's ``generate_videos`` long-running
    operation. ``duration_seconds`` is clamped to 8 seconds per DESIGN.md
    §7b. Polls every ``POLL_INTERVAL_SECONDS`` for up to ``MAX_WAIT_SECONDS``.

    Args:
        prompt: Video description from the Architect's video_brief.
        duration_seconds: 1-8. Values above 8 are clamped to 8.
        aspect_ratio: Per video_brief; defaults to ``"16:9"``.

    Returns:
        ``bytes``: MP4-encoded video data.

    Raises:
        RuntimeError: on timeout, error, or when the model returns no videos.
    """
    duration = max(1, min(int(duration_seconds), MAX_DURATION_SECONDS))

    client = _client()
    operation = client.models.generate_videos(
        model=DEFAULT_MODEL,
        prompt=prompt,
        config=types.GenerateVideosConfig(
            aspect_ratio=aspect_ratio,
            duration_seconds=duration,
            number_of_videos=1,
        ),
    )

    elapsed = 0
    while not getattr(operation, "done", False):
        if elapsed >= MAX_WAIT_SECONDS:
            raise RuntimeError(
                f"Veo generation timed out after {MAX_WAIT_SECONDS}s"
            )
        time.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS
        operation = client.operations.get(operation)

    if getattr(operation, "error", None):
        raise RuntimeError(f"Veo generation failed: {operation.error}")

    response = getattr(operation, "response", None)
    videos = getattr(response, "generated_videos", None) or []
    if not videos:
        raise RuntimeError("Veo returned no videos")
    return videos[0].video.video_bytes


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set; required for video generation")
    return value
