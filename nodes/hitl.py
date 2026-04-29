"""HITL function nodes — topic_gate_request + editor_request.
See DESIGN.v2.md §6.3.1 + §6.9.1.

Both nodes:
  1. Post a Telegram message with inline-keyboard buttons (via
     ``tools/telegram.py``).
  2. Yield a ``RequestInput`` keyed to a stable ``interrupt_id`` so the
     bridge can resume the session via ``FunctionResponse`` (§8.3).

If the Telegram POST fails, the node fails fast and the workflow ends
with an error rather than pausing without an operator-visible message.
Per §12.2 decision 1 (no retry-with-backoff in v2).
"""

import base64
import hashlib
import logging

from google.adk import Context
from google.adk.events import RequestInput

logger = logging.getLogger(__name__)


def _short_hash(text: str, length: int = 12) -> str:
    """SHA-256, base32-encoded, lowercased, truncated. See §8.1."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return base64.b32encode(digest).decode("ascii").lower()[:length]


def topic_gate_request(node_input, ctx: Context):
    """§6.3.1 — post Telegram + yield RequestInput; pause workflow."""
    chosen = ctx.state["chosen_release"]
    chosen_dict = chosen if isinstance(chosen, dict) else chosen.model_dump(mode="json")
    interrupt_id = f"topic-gate-{_short_hash(chosen_dict['url'])}"

    from tools.telegram import post_topic_approval
    post_topic_approval(
        chosen=chosen_dict,
        session_id=ctx.session.id,
        interrupt_id=interrupt_id,
    )

    yield RequestInput(
        interrupt_id=interrupt_id,
        payload=chosen_dict,
        message=(
            f"Topic Gate: approve {chosen_dict.get('title')!r}? "
            f"(score={chosen_dict.get('score')}, source={chosen_dict.get('source')})"
        ),
    )


def editor_request(node_input, ctx: Context):
    """§6.9.1 — post Telegram + yield RequestInput; pause workflow.

    ``interrupt_id`` includes ``editor_iterations`` so the bridge
    disambiguates "approve revision N" from "approve revision N+1".
    """
    chosen = ctx.state["chosen_release"]
    chosen_dict = chosen if isinstance(chosen, dict) else chosen.model_dump(mode="json")
    iter_count = ctx.state.get("editor_iterations", 0)
    interrupt_id = f"editor-{ctx.session.id[:8]}-{iter_count}"

    draft = ctx.state.get("draft")
    draft_preview = draft.markdown if draft else ""
    images = ctx.state.get("image_assets", []) or []
    image_urls = [img.url for img in images] if images else []
    video_asset = ctx.state.get("video_asset")
    video_url = video_asset.gif_url if video_asset else None
    repo = ctx.state.get("starter_repo")
    repo_url = repo.url if repo else None

    from tools.telegram import post_editor_review
    post_editor_review(
        chosen=chosen_dict,
        draft_preview=draft_preview,
        image_urls=image_urls,
        video_url=video_url,
        repo_url=repo_url,
        session_id=ctx.session.id,
        interrupt_id=interrupt_id,
    )

    yield RequestInput(
        interrupt_id=interrupt_id,
        payload={
            "draft_iteration":   draft.iteration if draft else None,
            "editor_iterations": iter_count,
        },
        message=f"Editor: {chosen_dict.get('title')!r} — approve, revise, or reject?",
    )
