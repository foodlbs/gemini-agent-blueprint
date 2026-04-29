"""Video Asset Agent — generates the demo MP4, GIF, and poster frame.

DESIGN.md §7b: Gemini 3.1 Flash, four tools (``generate_video``,
``convert_to_gif``, ``extract_first_frame``, ``upload_to_gcs``). The
first instruction line is a verbatim early-exit on
``needs_video=False`` or missing ``video_brief`` — without it, the agent
would burn ~$2-3 of Veo compute on an article that doesn't need motion.
"""

from google.adk.agents import LlmAgent

from shared.prompts import VIDEO_ASSET_INSTRUCTION
from tools.gcs import upload_to_gcs
from tools.veo import generate_video
from tools.video_processing import convert_to_gif, extract_first_frame


video_asset_agent = LlmAgent(
    name="video_asset_agent",
    model="gemini-3.1-flash-lite-preview",
    instruction=VIDEO_ASSET_INSTRUCTION,
    tools=[generate_video, convert_to_gif, extract_first_frame, upload_to_gcs],
    output_key="video_asset",
)
