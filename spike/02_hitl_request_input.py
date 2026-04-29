"""Spike test #2 — RequestInput pause/resume mechanics.

Goal: confirm a Workflow node can yield ``RequestInput``, the workflow
suspends, and a follow-up call to ``runner.run_async`` with a response
message resumes the workflow from where it left off — with the response
flowing into the next node.

This is the foundation for replacing our Telegram polling with the
managed HITL pattern. If this works, our Topic Gate and Editor agents
become a single ``RequestInput``-yielding function node each.

Pass criteria:
- First ``run_async`` call returns events ending with a RequestInput-shaped
  event (we can detect interrupt via event.actions.request_task or similar).
- Second ``run_async`` call on the SAME session_id with a response message
  resumes the workflow and produces the post-pause output.

Run::

    cd spike && uv run --no-project --with google-adk==2.0.0b1 \
        --with google-cloud-aiplatform python 02_hitl_request_input.py
"""

from __future__ import annotations

import asyncio
import json

from google.adk import Context, Event, Workflow
from google.adk.events import RequestInput
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types


# ---------------------------------------------------------------------------
# Function nodes
# ---------------------------------------------------------------------------


def setup(node_input: str, ctx: Context) -> Event:
    """Stand-in for Scout/Triage — pretends to have chosen a release."""
    chosen = {
        "title": "Anthropic Skills SDK",
        "url": "https://anthropic.com/skills",
        "score": 90,
    }
    ctx.state["chosen_release"] = chosen
    return Event(output=chosen)


def request_topic_approval(node_input, ctx: Context):
    """Pause the workflow and ask the human to approve the topic.

    Yields a ``RequestInput`` event. The workflow suspends until the
    session is resumed with a response message — that response becomes
    the input to the next node (``record_verdict``).
    """
    chosen = ctx.state.get("chosen_release", {})
    yield RequestInput(
        message=(
            f"Approve topic? title={chosen.get('title')!r}, "
            f"score={chosen.get('score')}. Reply with 'approve' or 'skip'."
        ),
        payload=chosen,
    )


def record_verdict(node_input, ctx: Context) -> Event:
    """Captures the human's response and writes it to state."""
    decision = "unknown"
    if isinstance(node_input, dict):
        decision = node_input.get("decision") or str(node_input)
    elif isinstance(node_input, str):
        decision = "approve" if "approve" in node_input.lower() else "skip"
    elif hasattr(node_input, "parts"):  # genai.types.Content
        text = " ".join(
            getattr(p, "text", "") for p in node_input.parts if getattr(p, "text", None)
        ).lower()
        decision = "approve" if "approve" in text else "skip"
    else:
        decision = str(node_input)
    ctx.state["topic_verdict"] = decision
    return Event(output={"verdict": decision, "title": ctx.state.get("chosen_release", {}).get("title")})


root_agent = Workflow(
    name="spike_hitl",
    edges=[
        ("START", setup, request_topic_approval, record_verdict),
    ],
)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def _summarize_event(event):
    out = getattr(event, "output", None)
    actions = getattr(event, "actions", None)
    # Probe ALL fields on actions to find what indicates a pause
    action_fields = {}
    if actions is not None:
        for f in (
            "request_task", "finish_task", "route", "escalate", "end_of_agent",
            "render_ui_widgets", "set_model_response", "agent_state",
            "requested_auth_configs", "requested_tool_confirmations",
            "transfer_to_agent",
        ):
            v = getattr(actions, f, None)
            if v not in (None, {}, [], False, ""):
                action_fields[f] = v
    state_delta = getattr(actions, "state_delta", None) if actions else None
    interrupt_ids = getattr(event, "interrupt_ids", None) or getattr(event, "long_running_tool_ids", None)
    content = getattr(event, "content", None)
    text_parts = ""
    if content and getattr(content, "parts", None):
        text_parts = " | ".join(
            f"{type(p).__name__}({list(p.model_dump().keys()) if hasattr(p,'model_dump') else 'raw'})"
            for p in content.parts
        )
    return {
        "author": getattr(event, "author", "?"),
        "output": out,
        "actions": action_fields or None,
        "state_delta": state_delta or None,
        "interrupt_ids": interrupt_ids or None,
        "content_parts": text_parts or None,
    }


async def main() -> None:
    runner = InMemoryRunner(agent=root_agent, app_name="spike_hitl")
    session = await runner.session_service.create_session(
        app_name="spike_hitl", user_id="spike-user"
    )
    print(f"session id: {session.id}\n")

    # ----- Pass 1 — run until pause --------------------------------------
    print("=== PASS 1: initial run, expect pause at request_topic_approval ===")
    msg1 = genai_types.Content(
        role="user",
        parts=[genai_types.Part.from_text(text="trigger")],
    )
    pass1_events = []
    async for event in runner.run_async(
        user_id="spike-user", session_id=session.id, new_message=msg1
    ):
        s = _summarize_event(event)
        print(f"  RUN  {s}")
        pass1_events.append(event)

    # Inspect session state + events post-pause — the canonical way to detect
    # that the workflow is paused on a RequestInput (not finished).
    sess = await runner.session_service.get_session(
        app_name="spike_hitl", user_id="spike-user", session_id=session.id
    )
    print(f"\nstate mid-pause: {dict(sess.state)}")
    print(f"session events ({len(sess.events)}):")
    paused = False
    for ev in sess.events:
        actions = getattr(ev, "actions", None)
        rt = getattr(actions, "request_task", None) if actions else None
        ft = getattr(actions, "finish_task", None) if actions else None
        ridx = getattr(ev, "long_running_tool_ids", None)
        if rt or ridx:
            paused = True
        print(
            f"  EV  author={getattr(ev,'author','?')} "
            f"request_task={rt} finish_task={ft} "
            f"long_running={ridx} output={getattr(ev,'output',None)!r:.80}"
        )
    print(f"\nPAUSED via session events? {paused}\n")

    # ----- Pass 2 — resume with a function_response keyed by interrupt_id --
    # The RequestInput's interrupt_id is reused as the function_call id; we
    # match it with a function_response Part to "answer" the request.
    interrupt_ids = []
    for ev in sess.events:
        ids = getattr(ev, "long_running_tool_ids", None)
        if ids:
            interrupt_ids.extend(ids)
    print(f"=== PASS 2: resume with function_response for interrupt {interrupt_ids} ===")
    if not interrupt_ids:
        print("NO INTERRUPT IDS — aborting pass 2")
        return
    interrupt_id = interrupt_ids[0]
    msg2 = genai_types.Content(
        role="user",
        parts=[
            genai_types.Part.from_function_response(
                name="request_topic_approval",
                response={"decision": "approve"},
            ).model_copy(update={"function_response": genai_types.FunctionResponse(
                id=interrupt_id, name="request_topic_approval",
                response={"decision": "approve"},
            )}),
        ],
    )
    async for event in runner.run_async(
        user_id="spike-user", session_id=session.id, new_message=msg2
    ):
        s = _summarize_event(event)
        print(f"  RUN  {s}")

    sess2 = await runner.session_service.get_session(
        app_name="spike_hitl", user_id="spike-user", session_id=session.id
    )
    print()
    print(f"final state: {dict(sess2.state)}")


if __name__ == "__main__":
    asyncio.run(main())
