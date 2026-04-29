"""Image Asset Agent — generates and uploads each image from the brief.

DESIGN.md §7a: Gemini 3.1 Flash, two tools (``generate_image``,
``upload_to_gcs``). Iterates ``state["image_brief"]``, builds an
``ImageAsset`` per spec, writes the list to ``state["image_assets"]``.
"""

from google.adk.agents import LlmAgent

from shared.prompts import IMAGE_ASSET_INSTRUCTION
from tools.gcs import upload_to_gcs
from tools.imagen import generate_image


image_asset_agent = LlmAgent(
    name="image_asset_agent",
    model="gemini-3.1-flash-lite-preview",
    instruction=IMAGE_ASSET_INSTRUCTION,
    tools=[generate_image, upload_to_gcs],
    output_key="image_assets",
)
