"""Spike test #3 — Memory Bank wiring.

Goal: confirm an ADK 2.0 agent can write a fact in session 1 and recall
it in session 2 via the managed memory service. We use
``InMemoryMemoryService`` so this runs offline; in production we swap in
``VertexAiMemoryBankService`` and the agent code stays the same.

Pass criteria:
- Session 1 transcripts get added to the memory service via
  ``add_session_to_memory``.
- Session 2 (different session_id) preloads matching memories at start —
  the agent's response references the fact stored in session 1.

Run::

    cd spike && uv run --no-project --with google-adk==2.0.0b1 \
        --with google-cloud-aiplatform python 03_memory_bank.py
"""

from __future__ import annotations

import asyncio

from google.adk import Agent
from google.adk.memory import InMemoryMemoryService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools import preload_memory
from google.genai import types as genai_types


memory_aware_agent = Agent(
    name="memory_aware",
    model="gemini-2.5-flash-lite",
    instruction=(
        "You answer questions about the user. If memory has been preloaded "
        "into your context (look for `<memory>` blocks), use it. Be concise."
    ),
    tools=[preload_memory],
)


async def _run_turn(runner, session_id: str, text: str, user_id: str = "user-1") -> str:
    msg = genai_types.Content(
        role="user",
        parts=[genai_types.Part.from_text(text=text)],
    )
    final_text = ""
    async for ev in runner.run_async(
        user_id=user_id, session_id=session_id, new_message=msg
    ):
        c = getattr(ev, "content", None)
        if c and getattr(c, "parts", None):
            for p in c.parts:
                t = getattr(p, "text", None)
                if t:
                    final_text += t
    return final_text


async def main() -> None:
    session_service = InMemorySessionService()
    memory_service = InMemoryMemoryService()
    runner = Runner(
        agent=memory_aware_agent,
        app_name="memory_spike",
        session_service=session_service,
        memory_service=memory_service,
    )

    # ----- Session 1 — teach the agent a fact ----------------------------
    sess1 = await session_service.create_session(app_name="memory_spike", user_id="user-1")
    print(f"=== Session 1 (id={sess1.id}) — teach a fact ===")
    response1 = await _run_turn(runner, sess1.id, "Hi! I live in Austin, Texas.")
    print(f"agent: {response1!r}\n")

    # Surface session 1 events into the memory service so future sessions can recall.
    sess1_filled = await session_service.get_session(
        app_name="memory_spike", user_id="user-1", session_id=sess1.id
    )
    await memory_service.add_session_to_memory(sess1_filled)
    print("Session 1 added to memory service.\n")

    # ----- Session 2 — fresh session, ask for the fact -------------------
    sess2 = await session_service.create_session(app_name="memory_spike", user_id="user-1")
    print(f"=== Session 2 (id={sess2.id}) — recall via preload_memory ===")
    response2 = await _run_turn(runner, sess2.id, "Where do I live?")
    print(f"agent: {response2!r}\n")

    # ----- Validate -------------------------------------------------------
    recalled = "austin" in response2.lower() or "texas" in response2.lower()
    print(f"PASS — recalled across sessions? {recalled}")


if __name__ == "__main__":
    asyncio.run(main())
