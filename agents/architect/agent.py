"""Architect — picks article type, outline, and asset/repo briefs.

DESIGN.md §5: Gemini 3.1 Pro, no tools. Reads ``chosen_release`` plus the
three research dossiers and produces a structured plan that the Writer,
Asset Agent, and Repo Builder fan out from.

Output mechanism
----------------
The LLM emits a single JSON object to ``state["architect_output"]`` (via
``output_key``). The ``after_agent_callback`` then splits that object
into the eight design-canonical state keys (``outline``, ``article_type``,
``needs_repo``, ``image_brief``, ``video_brief``, ``needs_video``,
``working_title``, ``working_subtitle``). A ``before_agent_callback``
enforces the chosen_release=None early-exit programmatically — the
instruction's first line is the LLM-level safeguard, the callback is
the runtime safeguard.
"""

import json
import logging
from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from shared.prompts import ARCHITECT_INSTRUCTION

logger = logging.getLogger(__name__)


ARCHITECT_OUTPUT_KEYS = (
    "article_type",
    "outline",
    "needs_repo",
    "needs_video",
    "image_brief",
    "video_brief",
    "working_title",
    "working_subtitle",
)


def _early_exit_if_no_chosen_release(
    callback_context: CallbackContext,
) -> Optional[types.Content]:
    """Skip the LLM call when chosen_release is None.

    Triage and Topic Gate both clear ``chosen_release`` to signal "stop";
    when that happens, the Architect (and every downstream agent) must
    bail without doing work. Returning a non-None ``Content`` from a
    before-agent callback short-circuits the LLM in ADK.
    """
    if callback_context.state.get("chosen_release") is None:
        return types.Content(
            parts=[types.Part(
                text="(architect skipped — chosen_release is None)"
            )]
        )
    return None


def _split_architect_output(
    callback_context: CallbackContext,
) -> Optional[types.Content]:
    """Split ``state["architect_output"]`` into the eight canonical state keys."""
    state = callback_context.state
    if state.get("chosen_release") is None:
        return None
    raw = state.get("architect_output")
    if raw is None:
        return None

    parsed = _coerce_to_dict(raw)
    if parsed is None:
        logger.warning(
            "Architect output was not parseable JSON; downstream agents will see "
            "missing state keys."
        )
        return None

    for key in ARCHITECT_OUTPUT_KEYS:
        if key in parsed:
            state[key] = parsed[key]
    return None


def _coerce_to_dict(value) -> Optional[dict]:
    """Accept dict / Pydantic / JSON-string / fenced-JSON-string."""
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, str):
        text = value.strip()
        # Strip a Markdown fence (```json ... ```) if the LLM wrapped it.
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


architect = LlmAgent(
    name="architect",
    model="gemini-3.1-pro-preview",
    instruction=ARCHITECT_INSTRUCTION,
    tools=[],
    output_key="architect_output",
    before_agent_callback=_early_exit_if_no_chosen_release,
    after_agent_callback=_split_architect_output,
)
