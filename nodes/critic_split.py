"""critic_split — parse critic_llm verdict + objective placeholder check.
See DESIGN.v2.md §6.6.3.

Parses the LLM's JSON verdict, but ALSO performs an objective string-search
for `<!--IMG:position-->` and `<!--VID:hero-->` markers and overrides the
LLM's accept → revise if marker counts don't match. Belt + suspenders for
the v1 Bug B2 class.

State contract (post-flat-Draft refactor):
  - reads:  state["draft"] (str — raw markdown), state["critic_raw"] (str)
  - writes: state["critic_verdict"] (literal), state["critic_feedback"] (str),
            state["writer_iterations"] (int, incremented)
"""

import json
import re

from google.adk import Context, Event

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)
_IMAGE_MARKER_RE = re.compile(r"<!--IMG:([^>]+?)-->", re.IGNORECASE)
_VIDEO_MARKER_RE = re.compile(r"<!--VID:[^>]+?-->", re.IGNORECASE)


def critic_split(node_input, ctx: Context) -> Event:
    """Parse `critic_raw` JSON; write top-level critic_*; bump writer_iterations."""
    raw = ctx.state.get("critic_raw") or ""
    cleaned = _FENCE_RE.sub("", raw).strip()
    if not cleaned.startswith("{"):
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        cleaned = match.group(0) if match else "{}"
    try:
        blob = json.loads(cleaned)
    except json.JSONDecodeError:
        blob = {}

    verdict = blob.get("verdict", "revise")
    if verdict not in ("accept", "revise"):
        verdict = "revise"
    feedback = blob.get("feedback", "") or ""

    # Objective placeholder check — overrides LLM accept if markers wrong.
    draft_md = ctx.state.get("draft") or ""
    image_briefs = ctx.state.get("image_briefs", [])
    needs_video  = ctx.state.get("needs_video", False)

    image_markers = _IMAGE_MARKER_RE.findall(draft_md)
    if len(image_markers) != len(image_briefs):
        verdict = "revise"
        feedback = (
            f"objective check: draft has {len(image_markers)} image markers, "
            f"expected {len(image_briefs)}. {feedback}"
        ).strip()

    has_video_marker = bool(_VIDEO_MARKER_RE.search(draft_md))
    if has_video_marker != needs_video:
        verdict = "revise"
        feedback = (
            f"objective check: video marker presence ({has_video_marker}) "
            f"does not match needs_video ({needs_video}). {feedback}"
        ).strip()

    ctx.state["critic_verdict"] = verdict
    ctx.state["critic_feedback"] = feedback
    ctx.state["writer_iterations"] = ctx.state.get("writer_iterations", 0) + 1
    return Event(output={
        "verdict": verdict,
        "iteration": ctx.state["writer_iterations"],
        "feedback_preview": feedback[:120],
    })
