"""Spike test #4 — Telegram → RequestInput bridge (design + working code).

Goal: prove we can route a Telegram callback button tap into a paused
ADK Workflow's ``RequestInput`` resume, completing the HITL loop.

This file is a SELF-CONTAINED simulation: instead of wiring a live
Telegram bot (requires tokens, public webhook URL, etc.), it stands up
a local FastAPI bridge and a fake "Telegram callback" emitter. The
plumbing — Telegram callback_data -> (session_id, interrupt_id, choice)
-> POST to runner.run_async with a FunctionResponse — is the real code
we'd ship.

Pattern in production:

    Topic Gate node (in our Workflow) yields:
        RequestInput(
            interrupt_id="topic-gate-<release_url>",   # stable, recoverable
            payload={"chosen_release": ..., "rationale": ...},
            message="...",
        )
    AND posts a Telegram message with three buttons whose callback_data
    encodes (session_id, interrupt_id, choice). Workflow pauses.

    Telegram webhook (this bridge) receives the callback_query, parses
    callback_data, calls the runner with a FunctionResponse keyed by
    interrupt_id and the user's choice.

    Workflow resumes. record_verdict() reads the choice and proceeds.

Run::

    cd spike && uv run --no-project --with google-adk==2.0.0b1 \
        --with google-cloud-aiplatform python 04_telegram_bridge.py
"""

from __future__ import annotations

import asyncio
import json
import urllib.parse

from google.adk import Context, Event, Workflow
from google.adk.events import RequestInput
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types


# ---------------------------------------------------------------------------
# 1. The Workflow (same shape as 02_hitl_request_input.py)
# ---------------------------------------------------------------------------


def setup(node_input, ctx: Context) -> Event:
    chosen = {
        "title": "Anthropic Skills SDK",
        "url": "https://anthropic.com/skills",
        "score": 90,
    }
    ctx.state["chosen_release"] = chosen
    return Event(output=chosen)


def topic_gate_request(node_input, ctx: Context):
    """Yields RequestInput AND prints the Telegram message we'd send.

    In production, this also calls the Telegram Bot API to post a message
    with three inline-keyboard buttons whose callback_data is built from
    (session_id, interrupt_id, choice). For this spike we just print it.
    """
    chosen = ctx.state["chosen_release"]
    interrupt_id = f"topic-gate-{chosen['url']}"
    session_id = ctx.session.id  # available on Context
    print(
        f"  [TELEGRAM SIMULATION] would post:\n"
        f"    title:  {chosen['title']}\n"
        f"    score:  {chosen['score']}\n"
        f"    buttons (callback_data):\n"
        f"      Approve  -> {_callback_data(session_id, interrupt_id, 'approve')}\n"
        f"      Skip     -> {_callback_data(session_id, interrupt_id, 'skip')}\n"
        f"      Revise   -> {_callback_data(session_id, interrupt_id, 'revise')}\n"
    )
    yield RequestInput(
        interrupt_id=interrupt_id,
        payload=chosen,
        message="Approve topic? (Telegram buttons posted)",
    )


def record_verdict(node_input, ctx: Context) -> Event:
    decision = node_input.get("decision") if isinstance(node_input, dict) else str(node_input)
    ctx.state["topic_verdict"] = decision
    return Event(output={"verdict": decision})


root_agent = Workflow(
    name="spike_telegram_bridge",
    edges=[("START", setup, topic_gate_request, record_verdict)],
)


# ---------------------------------------------------------------------------
# 2. The bridge — what the Telegram webhook handler would do.
# ---------------------------------------------------------------------------


def _callback_data(session_id: str, interrupt_id: str, choice: str) -> str:
    """Encode the data Telegram echoes back when a button is tapped.

    Telegram caps callback_data at 64 bytes. We use a short scheme:
    ``<session_id>|<choice>|<interrupt_id_short>``. In production the
    interrupt_id is shortened to 8 chars and the (session, full_id)
    mapping is kept in a small KV store — not in callback_data.
    """
    # For the spike we can fit the full IDs.
    return f"{session_id[:8]}|{choice}|{interrupt_id[:30]}"


def parse_callback_data(data: str) -> tuple[str, str, str]:
    """Inverse of _callback_data. Returns (session_id_prefix, choice, interrupt_id_prefix)."""
    parts = data.split("|", 2)
    if len(parts) != 3:
        raise ValueError(f"bad callback_data: {data!r}")
    return parts[0], parts[1], parts[2]


async def telegram_webhook_handler(
    callback_data: str,
    runner: InMemoryRunner,
    user_id: str,
    full_session_id: str,
    full_interrupt_id: str,
) -> dict:
    """The actual webhook handler — what FastAPI/aiohttp would call.

    In production:
      - Telegram POSTs to /webhook with the callback_query body
      - Handler extracts callback_data + user info
      - Looks up full session_id and interrupt_id from our KV store
        (keyed by the short prefixes we packed into callback_data)
      - Calls runner.run_async with a function_response
    """
    sess_pref, choice, interrupt_pref = parse_callback_data(callback_data)
    assert full_session_id.startswith(sess_pref), "session prefix mismatch"
    assert full_interrupt_id.startswith(interrupt_pref), "interrupt prefix mismatch"

    msg = genai_types.Content(
        role="user",
        parts=[
            genai_types.Part(function_response=genai_types.FunctionResponse(
                id=full_interrupt_id,
                name="topic_gate_request",
                response={"decision": choice},
            )),
        ],
    )
    final_state: dict = {}
    async for ev in runner.run_async(
        user_id=user_id, session_id=full_session_id, new_message=msg
    ):
        c = getattr(ev, "content", None)
        # We just collect — the final state is the source of truth.
    sess = await runner.session_service.get_session(
        app_name=runner.app_name, user_id=user_id, session_id=full_session_id
    )
    return dict(sess.state)


# ---------------------------------------------------------------------------
# 3. Driver — simulate a full pause-then-resume cycle.
# ---------------------------------------------------------------------------


async def main() -> None:
    runner = InMemoryRunner(agent=root_agent, app_name="spike_tg")
    sess = await runner.session_service.create_session(
        app_name="spike_tg", user_id="user-1"
    )
    print(f"session id: {sess.id}\n")

    # ----- Pause ---------------------------------------------------------
    print("=== Pass 1: workflow runs until Telegram-emitting RequestInput ===")
    msg1 = genai_types.Content(role="user", parts=[genai_types.Part.from_text(text="trigger")])
    async for _ in runner.run_async(
        user_id="user-1", session_id=sess.id, new_message=msg1
    ):
        pass
    paused = await runner.session_service.get_session(
        app_name="spike_tg", user_id="user-1", session_id=sess.id
    )
    interrupt_ids = []
    for ev in paused.events:
        for iid in getattr(ev, "long_running_tool_ids", None) or []:
            interrupt_ids.append(iid)
    if not interrupt_ids:
        print("FAIL — no interrupt observed")
        return
    full_interrupt_id = interrupt_ids[0]
    print(f"\nworkflow paused, interrupt_id={full_interrupt_id}\n")

    # ----- Simulate the Telegram tap -------------------------------------
    cb = _callback_data(sess.id, full_interrupt_id, "approve")
    print(f"=== Pass 2: simulated Telegram callback_data={cb!r} ===")
    final = await telegram_webhook_handler(
        callback_data=cb,
        runner=runner,
        user_id="user-1",
        full_session_id=sess.id,
        full_interrupt_id=full_interrupt_id,
    )
    print(f"\nfinal session state: {final}")
    print(
        f"\nPASS — bridge round-trip {'OK' if final.get('topic_verdict') == 'approve' else 'FAILED'}"
    )


if __name__ == "__main__":
    asyncio.run(main())
