"""Image asset generation as a function node — replaces the LlmAgent.

The previous LlmAgent version blew up the model context: Imagen
returns raw PNG bytes (~1MB each) as the function_response payload,
which accumulated in the LLM's history and pushed past the
1,048,576-token cap by the second call.

This function node iterates briefs deterministically, calls Imagen +
GCS directly, and writes a typed list[ImageAsset] to state — no LLM
involved, no context bloat, no tool-hallucination risk.
"""

from __future__ import annotations

import logging
from typing import Any

from google.adk import Context, Event

logger = logging.getLogger(__name__)


def image_asset_node(node_input, ctx: Context) -> Event:
    """Generate one image per brief; upload to GCS; write list[ImageAsset]."""
    from shared.models import ImageAsset
    from tools.gcs import upload_to_gcs
    from tools.imagen import generate_image

    chosen = ctx.state.get("chosen_release") or {}
    chosen_dict = chosen if isinstance(chosen, dict) else chosen.model_dump(mode="json")
    chosen_title = chosen_dict.get("title", "")

    briefs = ctx.state.get("image_briefs") or []
    cycle_id = ctx.session.id[:8]

    assets: list[ImageAsset] = []
    successes = 0
    failures = 0

    for brief in briefs:
        brief_dict = brief if isinstance(brief, dict) else brief.model_dump(mode="json")
        position = brief_dict.get("position", "")
        description = brief_dict.get("description", "")
        style = brief_dict.get("style", "illustration")
        aspect_ratio = brief_dict.get("aspect_ratio", "16:9")

        prompt = f"{style} of {description} (context: {chosen_title})"
        slug = f"{cycle_id}/image-{position}.png"

        try:
            png_bytes = generate_image(
                prompt=prompt, aspect_ratio=aspect_ratio, style=style,
            )
        except Exception as e:
            logger.warning(
                "image_asset_node: generate_image failed for %r: %s",
                position, e,
            )
            assets.append(ImageAsset(
                position=position,
                url="",
                alt_text="(image generation failed)",
                aspect_ratio=aspect_ratio,
            ))
            failures += 1
            continue

        try:
            url = upload_to_gcs(
                bytes_data=png_bytes, slug=slug, content_type="image/png",
            )
        except Exception as e:
            logger.warning(
                "image_asset_node: GCS upload failed for %r: %s",
                position, e,
            )
            assets.append(ImageAsset(
                position=position,
                url="",
                alt_text="(image upload failed)",
                aspect_ratio=aspect_ratio,
            ))
            failures += 1
            continue

        assets.append(ImageAsset(
            position=position,
            url=url,
            alt_text=f"{style} illustration for {chosen_title}",
            aspect_ratio=aspect_ratio,
        ))
        successes += 1

    ctx.state["image_assets"] = assets
    return Event(output={
        "image_count":     len(assets),
        "successes":       successes,
        "failures":        failures,
        "first_url":       assets[0].url if assets else None,
    })
