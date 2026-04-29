"""Spike test #1 — ADK 2.0 Workflow basics.

Goal: confirm that the graph-based ``Workflow`` executes a sequence of
function nodes + an LlmAgent end-to-end, the way ``ambient-expense-agent``
shows. This is the FOUNDATION — every other spike test depends on it.

Pass criteria:
- Workflow runs without import / construction errors.
- Function nodes receive prior node output and return ``Event`` objects.
- An LlmAgent in the middle of the graph produces text.
- Conditional routing via the dict-edge form selects the right branch.

Run locally::

    cd spike && uv run --no-project --with google-adk==2.0.0b1 \
        --with google-cloud-aiplatform python 01_workflow_basics.py
"""

from __future__ import annotations

import asyncio
import json
import os

from google.adk import Agent, Context, Event, Workflow
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types


# ---------------------------------------------------------------------------
# Function nodes — pure Python, no LLM. Must return google.adk.Event.
# ---------------------------------------------------------------------------


def parse_input(node_input: str) -> Event:
    """Pretend we received a Pub/Sub trigger; pull a release out of it."""
    try:
        payload = json.loads(node_input)
    except (json.JSONDecodeError, TypeError):
        payload = {"score": 0, "title": node_input or "(empty)"}
    return Event(output=payload)


def route_by_score(node_input: dict, ctx: Context) -> Event:
    """Conditional routing: high-score releases go to the LLM summarizer,
    low-score ones short-circuit to a no-op skip node.

    Routes are emitted via ``ctx.route = "BRANCH"`` (the dict-edge form
    matches on this) — returning ``Event(output="BRANCH")`` alone does
    NOT trigger conditional routing in ADK 2.0b1.
    """
    ctx.state["release"] = node_input
    score = float(node_input.get("score", 0))
    branch = "HIGH_SIG" if score >= 70 else "SKIP"
    ctx.route = branch
    return Event(output={"branch": branch, "score": score})


def skip_node(node_input, ctx: Context) -> Event:
    """Short-circuit branch — stand-in for our Triage skip path."""
    release = ctx.state.get("release", {})
    return Event(output={
        "status": "skipped",
        "reason": "score below threshold",
        "title": release.get("title"),
    })


def finalize(node_input, ctx: Context) -> Event:
    """End node for the high-significance branch."""
    release = ctx.state.get("release", {})
    summary = node_input if isinstance(node_input, str) else str(node_input)
    return Event(output={
        "status": "summarized",
        "title": release.get("title"),
        "score": release.get("score"),
        "summary_preview": summary[:200],
    })


# ---------------------------------------------------------------------------
# LLM agent node — invoked only on the HIGH_SIG branch.
# ---------------------------------------------------------------------------

summarizer = Agent(
    name="summarizer",
    model="gemini-2.5-flash-lite",
    mode="single_turn",
    instruction=(
        "You are a release-summary writer. The input is a JSON object with "
        "`title` and `score`. Produce ONE short sentence describing why this "
        "release matters. Do not call any tools."
    ),
)


# ---------------------------------------------------------------------------
# Graph definition — this is the whole point of the spike.
# ---------------------------------------------------------------------------

root_agent = Workflow(
    name="spike_workflow_basics",
    edges=[
        ("START", parse_input, route_by_score),
        (route_by_score, {
            "HIGH_SIG": summarizer,
            "SKIP": skip_node,
        }),
        (summarizer, finalize),
    ],
)


# ---------------------------------------------------------------------------
# Driver — run two cases, print outcomes.
# ---------------------------------------------------------------------------


async def _run(name: str, payload: dict) -> None:
    print(f"\n=== {name} ===")
    print(f"input: {payload}")
    runner = InMemoryRunner(agent=root_agent, app_name="spike")
    session = await runner.session_service.create_session(
        app_name="spike", user_id="spike-user"
    )
    final_output = None
    message = genai_types.Content(
        role="user",
        parts=[genai_types.Part.from_text(text=json.dumps(payload))],
    )
    try:
        async for event in runner.run_async(
            user_id="spike-user",
            session_id=session.id,
            new_message=message,
        ):
            author = getattr(event, "author", "?")
            out = getattr(event, "output", None)
            content = getattr(event, "content", None)
            text = ""
            if content and getattr(content, "parts", None):
                text = " ".join(
                    getattr(p, "text", "") for p in content.parts if getattr(p, "text", None)
                )
            # Dump every visible attr to find where the post-route node output lives.
            attrs = {
                k: getattr(event, k, None) for k in (
                    "author", "output", "branch", "state_delta", "actions",
                    "id", "invocation_id", "node", "name",
                )
            }
            short = {k: v for k, v in attrs.items() if v not in (None, {}, [], "")}
            print(f"  EVENT  {short}")
            if text:
                print(f"         text={text[:120]!r}")
            if out is not None:
                final_output = out
    except Exception as e:
        print(f"  EXCEPTION: {type(e).__name__}: {e}")
        raise
    print(f"final: {final_output}")


def main() -> None:
    if not os.environ.get("GOOGLE_CLOUD_PROJECT"):
        print(
            "WARN: GOOGLE_CLOUD_PROJECT not set — the LLM call on the HIGH_SIG "
            "branch will fail without Vertex auth."
        )
    asyncio.run(_run("low-significance (skip branch)", {"title": "Foo", "score": 30}))
    asyncio.run(_run("high-significance (summarize branch)", {
        "title": "Anthropic Skills SDK", "score": 90,
    }))


if __name__ == "__main__":
    main()
