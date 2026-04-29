"""architect_split — parses `_architect_raw` JSON blob into 5 typed state writes.
See DESIGN.v2.md §6.5.2.

Replaces v1's `after_agent_callback` JSON-blob parser with a named,
testable, type-safe function node."""

import json
import logging
import re

from google.adk import Context, Event

from shared.models import ImageBrief, Outline, OutlineSection, VideoBrief

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def architect_split(node_input, ctx: Context) -> Event:
    """Parse architect_llm's JSON blob → outline + image_briefs + ... 5 keys."""
    raw = ctx.state.get("architect_raw") or ""
    cleaned = _FENCE_RE.sub("", raw).strip()
    if not cleaned.startswith("{"):
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError(f"architect produced no JSON: {raw[:200]!r}")
        cleaned = match.group(0)

    try:
        blob = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"architect JSON invalid: {e}; raw={raw[:200]!r}") from e

    # Outline
    outline = Outline(**blob["outline"])
    if not outline.sections:
        raise ValueError("architect produced 0 sections")

    # Image briefs
    image_briefs = [ImageBrief(**b) for b in blob.get("image_briefs", [])]
    if not image_briefs:
        raise ValueError("architect produced 0 image_briefs")
    if len(image_briefs) > 4:
        logger.warning(
            "architect produced %d image_briefs; truncating to 4", len(image_briefs)
        )
        image_briefs = image_briefs[:4]
    if not any(b.position == "hero" for b in image_briefs):
        raise ValueError("architect did not produce a hero image_brief")

    # Video brief — gated on needs_video
    needs_video = bool(blob.get("needs_video", False))
    vb_dict = blob.get("video_brief")
    video_brief = VideoBrief(**vb_dict) if (needs_video and vb_dict) else None
    if needs_video and video_brief is None:
        logger.warning("needs_video=True but no video_brief; coercing needs_video=False")
        needs_video = False

    needs_repo = bool(blob.get("needs_repo", False))

    # Atomic state write
    ctx.state["outline"]      = outline
    ctx.state["image_briefs"] = image_briefs
    ctx.state["video_brief"]  = video_brief
    ctx.state["needs_video"]  = needs_video
    ctx.state["needs_repo"]   = needs_repo
    return Event(output={
        "sections": len(outline.sections),
        "images":   len(image_briefs),
        "needs_video": needs_video,
        "needs_repo":  needs_repo,
    })
