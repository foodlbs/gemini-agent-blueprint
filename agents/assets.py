"""Image asset agent — only the image side. See DESIGN.v2.md §6.7.1.

Video generation is deliberately a function node (nodes/video_asset.py)
in v2, NOT an LlmAgent — eliminates the Bug B2 class structurally."""

from google.adk import Agent

from tools.gcs import upload_to_gcs
from tools.imagen import generate_image


# TODO §6.7.1 — fill in IMAGE_ASSET_INSTRUCTION:
#   - One generate_image call per image_briefs entry, sequentially.
#   - Compose richer prompt: f"{style} of {description} (context: {title})".
#   - Per-image alt_text via LLM (one sentence describing the image).
#   - Failures produce placeholder ImageAsset(url="", alt_text="(image generation failed)")
image_asset_agent = Agent(
    name="image_asset_agent",
    model="gemini-3.1-flash",
    instruction=(
        "TODO §6.7.1 — for each image_brief, call generate_image then "
        "upload_to_gcs; emit ImageAsset list with alt_text per entry."
    ),
    tools=[generate_image, upload_to_gcs],
    output_key="image_assets",
)
