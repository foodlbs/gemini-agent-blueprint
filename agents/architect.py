"""Architect — produces the JSON blob parsed by nodes/architect_split.py.
See DESIGN.v2.md §6.5.1."""

from google.adk import Agent

from shared.prompts import ARCHITECT_INSTRUCTION


architect_llm = Agent(
    name="architect_llm",
    model="gemini-2.5-pro",
    instruction=ARCHITECT_INSTRUCTION,
    output_key="architect_raw",
)
