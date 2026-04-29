"""Editor — final QA, asset weaving, human approval, Memory Bank recording.

DESIGN.md §9: Gemini 3.1 Pro, three tools (``medium_format``,
``telegram_post_for_approval``, ``memory_bank_add_fact``). Entry point of
the Revision Loop — its verdict drives whether the loop continues or
exits.

State-mutation wiring
---------------------
The LLM emits a single JSON blob to ``state["editor_output_blob"]`` via
``output_key``. An ``after_agent_callback`` then:

- Splits the blob into the four design-canonical state keys:
  ``editor_verdict``, ``final_article``, ``human_feedback``,
  ``medium_draft_url``.
- Sets ``callback_context.actions.escalate = True`` for terminal verdicts
  (``approve``, ``reject``, ``pending_human``) — that breaks the parent
  ``LoopAgent`` per ADK's contract. ``revise`` does NOT escalate so the
  Revision Writer runs next.

A ``before_agent_callback`` enforces the chosen_release=None early exit
programmatically.

An ``after_tool_callback`` flips ``state["memory_bank_recorded"]`` to True
whenever the LLM calls ``memory_bank_add_fact``. This satisfies DESIGN.md
§9's "never re-add to Memory Bank if you've already added in a prior
iteration" constraint without the LLM having to track the flag itself —
the LLM's instruction reads the flag, the callback maintains it.
"""

import json
import logging
from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from shared.memory import memory_bank_add_fact
from shared.prompts import EDITOR_INSTRUCTION
from tools.medium import medium_format
from tools.telegram_approval import telegram_post_for_approval

logger = logging.getLogger(__name__)


EDITOR_OUTPUT_KEYS = (
    "editor_verdict",
    "final_article",
    "human_feedback",
    "medium_draft_url",
)

ESCALATE_VERDICTS = {"approve", "reject", "pending_human"}


def _early_exit_if_no_chosen_release(
    callback_context: CallbackContext,
) -> Optional[types.Content]:
    """Skip the LLM call when chosen_release is None."""
    if callback_context.state.get("chosen_release") is None:
        return types.Content(parts=[types.Part(
            text="(editor skipped — chosen_release is None)"
        )])
    return None


def _split_editor_output(
    callback_context: CallbackContext,
) -> Optional[types.Content]:
    """Split the LLM's JSON blob into state keys and apply escalate."""
    state = callback_context.state
    if state.get("chosen_release") is None:
        return None
    raw = state.get("editor_output_blob")
    if raw is None:
        return None

    parsed = _coerce_to_dict(raw)
    if parsed is None:
        logger.warning(
            "Editor output was not parseable JSON; downstream agents will see "
            "missing state keys."
        )
        return None

    for key in EDITOR_OUTPUT_KEYS:
        if key in parsed:
            state[key] = parsed[key]

    verdict = parsed.get("editor_verdict")
    if verdict in ESCALATE_VERDICTS:
        callback_context.actions.escalate = True
    return None


def _track_memory_bank_writes(
    tool: BaseTool,
    args: dict,
    tool_context: ToolContext,
    tool_response: dict,
) -> Optional[dict]:
    """After-tool callback: flip ``memory_bank_recorded`` when add_fact runs.

    The LLM is instructed to check ``state.get("memory_bank_recorded")``
    before calling memory_bank_add_fact. We set the flag here so the next
    iteration of the revision loop won't double-record.
    """
    if getattr(tool, "name", None) == "memory_bank_add_fact":
        tool_context.state["memory_bank_recorded"] = True
    return None


def _coerce_to_dict(value: Any) -> Optional[dict]:
    """Accept dict / Pydantic / JSON-string / fenced-JSON-string."""
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines)
        try:
            return json.loads(text)
        except (TypeError, json.JSONDecodeError):
            return None
    return None


editor = LlmAgent(
    name="editor",
    model="gemini-3.1-pro-preview",
    instruction=EDITOR_INSTRUCTION,
    tools=[medium_format, telegram_post_for_approval, memory_bank_add_fact],
    output_key="editor_output_blob",
    before_agent_callback=_early_exit_if_no_chosen_release,
    after_agent_callback=_split_editor_output,
    after_tool_callback=_track_memory_bank_writes,
)
