"""Helper tools that let agents write structured values into session state.

ADK's ``LlmAgent.output_key`` parameter dumps the model's raw text response
into ``state[key]`` — fine for plain-text outputs (markdown drafts) but
wrong for structured outputs (objects, lists, None) where downstream agents
need to type-check or branch on the value.

Vertex automatic function calling cannot infer JSON schemas for Pydantic
parameters (``list[Candidate]``, ``ChosenRelease``, etc.). The workaround
this module provides is to pass the value as a JSON-encoded string and
parse it server-side, keeping the tool's surface schema simple (``str``).

Per DESIGN.v2.md §12.2 (Bug B3 fix): for known-string state keys
(``skip_reason``, ``human_feedback``), the tool falls back to treating
``value_json`` as a plain string when JSON parsing fails. The LLM
sometimes calls ``write_state_json(key="skip_reason", value_json="...")``
with a bare string instead of the JSON-encoded form ``"\"...\""`` —
strict rejection here causes Triage to loop trying to "fix" something
that's actually fine.
"""

import json
import logging
from typing import Any

from google.adk.tools import ToolContext

logger = logging.getLogger(__name__)


# Keys whose values are stored as plain strings in PipelineState. If
# json.loads() fails on the LLM's input, accept it as the raw string
# rather than rejecting (Bug B3 v2 fix).
_STRING_FALLBACK_KEYS = frozenset({
    "skip_reason",
})

# Keys that follow first-write-wins semantics: once write_state_json
# has been called for one of these keys, subsequent calls return
# ok=True without changing state. Tracked via a hidden counter
# `_<key>_write_count` so that null and non-null first writes both lock.
#
# This stops Triage's known LLM looping behavior — flash/flash-lite
# often re-evaluates and re-writes its decision 4-10 times, sometimes
# transitioning from a valid candidate back to null mid-loop. The
# first decision is the one that downstream nodes route on; later
# writes only waste tokens.
# Map from sticky key to its companion counter field on PipelineState.
# Underscore-prefixed names cannot be used because Pydantic v2 treats
# them as private attributes (see Bug 2 in the v2 fixes log).
_STICKY_COUNTER_FIELDS: dict[str, str] = {
    "chosen_release": "chosen_release_write_count",
}
_STICKY_KEYS = frozenset(_STICKY_COUNTER_FIELDS)


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
            object like ``"{\"title\": \"...\", \"score\": 75}"``. For
            string-typed keys (``skip_reason``), a bare string value is
            also accepted and stored as-is.

    Returns:
        ``{"ok": True, "key": <key>}`` on success, or
        ``{"ok": False, "error": <message>}`` if ``value_json`` is not
        valid JSON AND the key is not in the string-fallback allowlist.
        For sticky keys (``chosen_release``) that already hold a non-null
        value, returns ``{"ok": True, "key": <key>, "skipped": "sticky"}``
        without modifying state.
    """
    if key in _STICKY_KEYS:
        ck = _STICKY_COUNTER_FIELDS[key]
        prior_count = int(tool_context.state.get(ck, 0))
        if prior_count >= 1:
            logger.info(
                "write_state_json: %s already written %d time(s); skipping "
                "(sticky-key first-write-wins policy)", key, prior_count,
            )
            # Return ok=False with a clear directive — the LLM treats
            # this as an error and (with the right instruction) stops
            # making more tool calls. ok=True with skipped=sticky is
            # too soft — flash/flash-lite ignore the success and keep
            # looping, stalling the workflow indefinitely.
            return {
                "ok": False,
                "key": key,
                "error": (
                    f"DECISION_ALREADY_FINALIZED: state['{key}'] was "
                    f"written {prior_count} time(s) earlier this turn. "
                    f"The decision is final and cannot be changed. "
                    f"Stop calling tools and end your response now."
                ),
            }

    try:
        parsed = json.loads(value_json) if value_json else None
    except json.JSONDecodeError as e:
        if key in _STRING_FALLBACK_KEYS:
            logger.info(
                "write_state_json: %s received plain string (not JSON), "
                "storing as-is per string-fallback policy", key,
            )
            tool_context.state[key] = value_json
            return {"ok": True, "key": key, "fallback": "string"}
        logger.warning("write_state_json invalid JSON for %s: %s", key, e)
        return {"ok": False, "error": f"Invalid JSON: {e}"}
    tool_context.state[key] = parsed
    if key in _STICKY_KEYS:
        ck = _STICKY_COUNTER_FIELDS[key]
        tool_context.state[ck] = int(tool_context.state.get(ck, 0)) + 1
    return {"ok": True, "key": key}
