"""Writer loop — drafter + critic. See DESIGN.v2.md §6.6.

`drafter` writes/rewrites the article markdown. `critic_llm` reviews
against the 8-item rubric and emits a JSON verdict (parsed by
nodes/critic_split.py)."""

from google.adk import Agent

from shared.prompts import CRITIC_INSTRUCTION, DRAFTER_INSTRUCTION


drafter = Agent(
    name="drafter",
    model="gemini-2.5-pro",
    instruction=DRAFTER_INSTRUCTION,
    output_key="draft",
)


critic_llm = Agent(
    name="critic_llm",
    model="gemini-2.5-flash-lite",
    instruction=CRITIC_INSTRUCTION,
    output_key="critic_raw",
)
