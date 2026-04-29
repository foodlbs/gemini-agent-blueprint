"""Triage — scores candidates, dedupes via Memory Bank, picks one (or none)."""

from google.adk.agents import LlmAgent

from shared.memory import memory_bank_search
from shared.prompts import TRIAGE_INSTRUCTION
from tools.state_helpers import write_state_json


triage = LlmAgent(
    name="triage",
    model="gemini-3.1-flash-lite-preview",
    instruction=TRIAGE_INSTRUCTION,
    tools=[memory_bank_search, write_state_json],
)
