"""video_asset_or_skip — function node, NOT an LlmAgent. See DESIGN.v2.md §6.7.2.

The needs_video guard is enforced HERE in code — no LLM in this node, so
prompt-following bugs (v1 Bug B2) are STRUCTURALLY IMPOSSIBLE.

v2 ships MP4-only per §7.7 Q8 — no GIF/poster derivation. The
gif_url and poster_url fields of VideoAsset stay equal to the MP4 URL
in v2; we add real ffmpeg-based derivation in v2.1 if a downstream
consumer needs it."""

import logging

from google.adk import Context, Event

from shared.models import VideoAsset
from tools.gcs import upload_to_gcs
from tools.veo import generate_video

logger = logging.getLogger(__name__)


def video_asset_or_skip(node_input, ctx: Context) -> Event:
    """Generate video iff needs_video=True; else write None and return."""
    if not ctx.state.get("needs_video"):
        ctx.state["video_asset"] = None
        return Event(output={"skipped": True, "reason": "needs_video=False"})

    brief = ctx.state.get("video_brief")
    if brief is None:
        logger.warning(
            "video_asset_or_skip: needs_video=True but video_brief is None; skipping"
        )
        ctx.state["video_asset"] = None
        return Event(output={"skipped": True, "reason": "no video_brief despite needs_video=True"})

    cycle_id = ctx.session.id[:8]
    try:
        mp4_bytes = generate_video(
            prompt=brief.description,
            duration_seconds=brief.duration_seconds,
            aspect_ratio=brief.aspect_ratio,
        )
    except Exception as e:
        logger.warning("Veo generation failed: %s — leaving video_asset=None", e)
        ctx.state["video_asset"] = None
        return Event(output={"skipped": True, "reason": f"veo_error: {e}"})

    mp4_url = upload_to_gcs(
        bytes_data=mp4_bytes,
        slug=f"{cycle_id}/video.mp4",
        content_type="video/mp4",
    )

    # v2 ships MP4-only per §7.7 Q8 — gif_url + poster_url default to MP4.
    ctx.state["video_asset"] = VideoAsset(
        mp4_url=mp4_url,
        gif_url=mp4_url,
        poster_url=mp4_url,
        duration_seconds=brief.duration_seconds,
    )
    return Event(output={"skipped": False, "duration_seconds": brief.duration_seconds})
