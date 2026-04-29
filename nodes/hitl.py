"""HITL function nodes — topic_gate_request + editor_request.
See DESIGN.v2.md §6.3.1 + §6.9.1.

Both nodes:
  1. Post a Telegram message with inline-keyboard buttons.
  2. Yield a `RequestInput` keyed to a stable `interrupt_id` so the
     bridge can resume the session via FunctionResponse (§8.3).

The actual Telegram post helpers live in `tools/telegram.py` (§7.3.1)
which is implemented in a later turn. Until then these stubs yield
the RequestInput without posting — the workflow will still pause but
the operator won't see a message. **Wire `tools/telegram.py` before
running end-to-end.**
"""

import hashlib
import base64
from google.adk import Context
from google.adk.events import RequestInput


def _short_hash(text: str, length: int = 12) -> str:
    """SHA-256, base32-encoded, lowercased, truncated. See §8.1."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return base64.b32encode(digest).decode("ascii").lower()[:length]


def topic_gate_request(node_input, ctx: Context):
    """§6.3.1 — post Telegram + yield RequestInput; pause workflow."""
    chosen = ctx.state["chosen_release"]
    interrupt_id = f"topic-gate-{_short_hash(chosen['url'])}"

    # TODO §7.3.1 — once tools/telegram.py exists, call:
    #     post_topic_approval(chosen=chosen, session_id=ctx.session.id,
    #                         interrupt_id=interrupt_id)

    yield RequestInput(
        interrupt_id=interrupt_id,
        payload=chosen,
        message=(
            f"Topic Gate: approve {chosen.get('title')!r}? "
            f"(score={chosen.get('score')}, source={chosen.get('source')})"
        ),
    )


def editor_request(node_input, ctx: Context):
    """§6.9.1 — post Telegram + yield RequestInput; pause workflow.

    interrupt_id includes editor_iterations so the bridge disambiguates
    "approve revision N" from "approve revision N+1".
    """
    chosen = ctx.state["chosen_release"]
    iter_count = ctx.state.get("editor_iterations", 0)
    interrupt_id = f"editor-{ctx.session.id[:8]}-{iter_count}"

    # TODO §7.3.1 — once tools/telegram.py exists, call:
    #     post_editor_review(chosen=chosen, draft_preview=draft.markdown[:500],
    #                        image_urls=..., video_url=..., repo_url=...,
    #                        session_id=ctx.session.id, interrupt_id=interrupt_id)

    yield RequestInput(
        interrupt_id=interrupt_id,
        payload={
            "draft_iteration": ctx.state["draft"].iteration if ctx.state.get("draft") else None,
            "editor_iterations": iter_count,
        },
        message=f"Editor: {chosen.get('title')!r} — approve, revise, or reject?",
    )
