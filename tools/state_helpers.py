"""Helper tools that let agents write structured values into session state.

ADK's ``LlmAgent.output_key`` parameter dumps the model's raw text response
into ``state[key]`` — fine for plain-text outputs (markdown drafts) but
wrong for structured outputs (objects, lists, None) where downstream agents
need to type-check or branch on the value.

Vertex automatic function calling cannot infer JSON schemas for Pydantic
parameters (``list[Candidate]``, ``ChosenRelease``, etc.). The workaround
this module provides is to pass the value as a JSON-encoded string and
parse it server-side, keeping the tool's surface schema simple (``str``).
"""

import json
import logging
from typing import Any

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)


def write_state_json(
    key: str,
    value_json: str,
    tool_context: ToolContext,
) -> dict[str, Any]:
    """Write a JSON-serializable value into session state under ``key``.

    Use this when an agent needs to persist a structured value (object,
    list, None) that downstream agents will read from ``state[key]``.

    Args:
        key: The state key to write (for example ``"chosen_release"``,
            ``"topic_verdict"``, ``"skip_reason"``).
        value_json: A JSON-encoded string. Examples: ``"null"`` to write
            None; ``"\"approve\""`` to write the literal string; or a JSON
            object like ``"{\"title\": \"...\", \"score\": 75}"``.

    Returns:
        ``{"ok": True, "key": <key>}`` on success, or
        ``{"ok": False, "error": <message>}`` if ``value_json`` is not
        valid JSON.
    """
    try:
        parsed = json.loads(value_json)
    except json.JSONDecodeError as e:
        logger.warning("write_state_json invalid JSON for %s: %s", key, e)
        return {"ok": False, "error": f"Invalid JSON: {e}"}
    tool_context.state[key] = parsed
    return {"ok": True, "key": key}
