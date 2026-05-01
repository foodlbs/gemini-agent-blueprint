"""Triage — picks one candidate or skips. See DESIGN.v2.md §6.2.1.

Triage tools:
  - memory_bank_search: dedup against `covered` and `human-rejected` facts.
  - write_state_json: persist chosen_release + skip_reason as typed state.
"""

from google.adk import Agent
from google.genai import types as genai_types

from shared.prompts import TRIAGE_INSTRUCTION
from tools.memory import memory_bank_search
from tools.state_helpers import write_state_json


# Same hallucination protection as Scout — VALIDATED mode + allowlist
# stops flash-lite from inventing `default_api.X` calls.
_TRIAGE_TOOLS_CONFIG = genai_types.GenerateContentConfig(
    tool_config=genai_types.ToolConfig(
        function_calling_config=genai_types.FunctionCallingConfig(
            mode=genai_types.FunctionCallingConfigMode.VALIDATED,
            allowed_function_names=["memory_bank_search", "write_state_json"],
        ),
    ),
)


triage = Agent(
    name="triage",
    # flash-lite, not flash. Both models ignore "stop after the two
    # writes" prompt directives and loop 4-10 times. The sticky-key
    # counter in `tools/state_helpers.write_state_json` prevents the
    # repeated writes from corrupting chosen_release. flash-lite has
    # ~10x higher per-minute quota than flash, which matters because
    # the wasted LLM calls (post-sticky-lock) still count against
    # quota. flash hits 429 in 1-2 cycles; flash-lite handles ~20.
    model="gemini-2.5-flash-lite",
    instruction=TRIAGE_INSTRUCTION,
    tools=[memory_bank_search, write_state_json],
    generate_content_config=_TRIAGE_TOOLS_CONFIG,
)
