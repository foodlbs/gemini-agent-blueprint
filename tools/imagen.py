"""Image generation via Vertex AI (Nano Banana 2)."""

import logging
import os
from typing import Optional

from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

DEFAULT_MODEL = os.environ.get("NANO_BANANA_MODEL", "imagen-4.0-fast-generate-001")

_STYLE_HINTS = {
    "photoreal": "photorealistic, high detail, natural lighting",
    "diagram": "clean technical diagram, flat vector, minimal palette",
    "illustration": "editorial illustration, modern composition",
    "screenshot": "developer terminal screenshot, monospace font, dark theme",
}

_client_singleton: Optional[genai.Client] = None


def _client() -> genai.Client:
    """Lazily build a single Vertex AI GenAI client."""
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


def generate_image(
    prompt: str,
    aspect_ratio: str = "16:9",
    style: str = "photoreal",
) -> bytes:
    """Generate one image and return its PNG bytes.

    Calls Nano Banana 2 via Vertex AI's ``generate_images`` API. The
    style is appended to the prompt as a stylistic hint; ADK passes the
    Architect's per-image ``style`` value through unchanged.

    Args:
        prompt: The image description.
        aspect_ratio: ``"16:9"`` or ``"4:3"`` per DESIGN.md §5.
        style: One of ``photoreal | diagram | illustration | screenshot``.

    Returns:
        ``bytes``: PNG-encoded image data.

    Raises:
        RuntimeError: when the model returns no images or env vars are missing.
    """
    style_hint = _STYLE_HINTS.get(style, style)
    full_prompt = f"{prompt}. Style: {style_hint}."

    response = _client().models.generate_images(
        model=DEFAULT_MODEL,
        prompt=full_prompt,
        config=types.GenerateImagesConfig(
            aspect_ratio=aspect_ratio,
            number_of_images=1,
            output_mime_type="image/png",
        ),
    )

    images = getattr(response, "generated_images", None) or []
    if not images:
        raise RuntimeError("Nano Banana 2 returned no images")
    return images[0].image.image_bytes


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set; required for image generation")
    return value
