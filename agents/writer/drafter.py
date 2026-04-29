"""Drafter — produces article markdown following the Architect's outline.

DESIGN.md §6a: Gemini 3.1 Pro, no tools. Inserts ``<!-- IMAGE: <position> -->``
markers for every entry in ``state["image_brief"]`` and ``<!-- VIDEO: hero -->``
when ``state["needs_video"]`` is True. The Critic verifies marker presence
before scoring; missing markers force a revision.
"""

from google.adk.agents import LlmAgent

from shared.prompts import DRAFTER_INSTRUCTION


drafter = LlmAgent(
    name="drafter",
    model="gemini-3.1-pro-preview",
    instruction=DRAFTER_INSTRUCTION,
    tools=[],
    output_key="draft",
)
