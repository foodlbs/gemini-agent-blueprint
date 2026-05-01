"""Revision Writer — rewrites draft per human_feedback. See DESIGN.v2.md §6.10.

Loops back to nodes/hitl.py:editor_request, NOT to critic_llm — once the
human is involved, the structural rubric is bypassed."""

from google.adk import Agent

from shared.prompts import REVISION_WRITER_INSTRUCTION


revision_writer = Agent(
    name="revision_writer",
    model="gemini-2.5-pro",
    instruction=REVISION_WRITER_INSTRUCTION,
    output_key="draft",
)
