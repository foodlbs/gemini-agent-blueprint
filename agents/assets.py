"""Image asset agent — only the image side. See DESIGN.v2.md §6.7.1.

Video generation is deliberately a function node (nodes/video_asset.py)
in v2, NOT an LlmAgent — eliminates the Bug B2 class structurally."""

from google.adk import Agent

from shared.prompts import IMAGE_ASSET_INSTRUCTION
from tools.gcs import upload_to_gcs
from tools.imagen import generate_image


image_asset_agent = Agent(
    name="image_asset_agent",
    model="gemini-3.1-flash-lite-preview",
    instruction=IMAGE_ASSET_INSTRUCTION,
    tools=[generate_image, upload_to_gcs],
    output_key="image_assets",
)
