"""Triage — picks one candidate or skips. See DESIGN.v2.md §6.2.1.

Triage tools:
  - memory_bank_search: dedup against `covered` and `human-rejected` facts.
  - write_state_json: persist chosen_release + skip_reason as typed state.
"""

from google.adk import Agent

from shared.prompts import TRIAGE_INSTRUCTION
from tools.memory import memory_bank_search
from tools.state_helpers import write_state_json


triage = Agent(
    name="triage",
    model="gemini-3.1-flash-lite-preview",
    instruction=TRIAGE_INSTRUCTION,
    tools=[memory_bank_search, write_state_json],
)
