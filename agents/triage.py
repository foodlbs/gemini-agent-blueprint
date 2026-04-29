"""Triage — picks one candidate or skips. See DESIGN.v2.md §6.2.1.

Triage tools:
  - memory_bank_search: dedup against `covered` and `human-rejected` facts.
  - write_state_json: persist chosen_release + skip_reason as typed state.
"""

from google.adk import Agent

from tools.state_helpers import write_state_json

# tools/memory.py is implemented in a later turn (§7.2). Until then, Triage
# can be defined without the memory tool — the workflow won't run end-to-end
# but the import + Workflow construction will succeed.
try:
    from tools.memory import memory_bank_search
    _MEMORY_TOOL = [memory_bank_search]
except ImportError:
    _MEMORY_TOOL = []  # TODO §7.2 — remove this fallback when tools/memory.py lands

# TODO §6.2.1 — fill in the rubric prompt: scoring (40+20+20+20),
# novelty check via memory_bank_search, write_state_json mandate.
triage = Agent(
    name="triage",
    model="gemini-3.1-flash",
    instruction=(
        "TODO §6.2.1 — score candidates on the 40+20+20+20 rubric, "
        "check novelty via memory_bank_search, persist chosen_release + "
        "skip_reason via write_state_json."
    ),
    tools=[*_MEMORY_TOOL, write_state_json],
)
