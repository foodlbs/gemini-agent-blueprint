"""Topic Gate — first human gate. Posts the chosen release to Telegram and
captures the human's approve/skip verdict.

Wiring note (state mutation gap): the DESIGN.md §3 instruction tells the
LLM to "set state['chosen_release'] = None" on skip/timeout, but an
``LlmAgent`` with two tools has no direct way to mutate state keys other
than its ``output_key``. The ``_apply_topic_verdict`` after-agent callback
fills that gap — once the LLM has written ``state["topic_verdict"]``, the
callback applies the per-verdict cleanup the design requires.
"""

from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from shared.memory import memory_bank_add_fact
from shared.prompts import TOPIC_GATE_INSTRUCTION
from tools.state_helpers import write_state_json
from tools.telegram_approval import telegram_post_topic_for_approval


def _apply_topic_verdict(
    callback_context: CallbackContext,
) -> Optional[types.Content]:
    """Apply per-verdict state mutations after the LLM finishes.

    Reads ``state["topic_verdict"]`` (written via output_key) and:
    - skip → clears ``chosen_release``, sets ``skip_reason="human-rejected"``.
    - timeout → clears ``chosen_release``, sets ``skip_reason="topic-gate-timeout"``.
    - approve → no-op (chosen_release stays for downstream agents).
    """
    state = callback_context.state
    verdict = state.get("topic_verdict")
    if verdict == "skip":
        state["chosen_release"] = None
        state["skip_reason"] = "human-rejected"
    elif verdict == "timeout":
        state["chosen_release"] = None
        state["skip_reason"] = "topic-gate-timeout"
    return None


topic_gate = LlmAgent(
    name="topic_gate",
    model="gemini-3.1-flash-lite-preview",
    instruction=TOPIC_GATE_INSTRUCTION,
    tools=[telegram_post_topic_for_approval, memory_bank_add_fact, write_state_json],
    after_agent_callback=_apply_topic_verdict,
)
