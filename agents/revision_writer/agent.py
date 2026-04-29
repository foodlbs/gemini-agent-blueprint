"""Revision Writer — rewrites the draft to incorporate human feedback.

DESIGN.md §10: Gemini 3.1 Pro, no tools — pure rewriting over state. Only
runs when ``state["editor_verdict"] == "revise"`` and ``state["human_feedback"]``
is non-empty; otherwise exits immediately. After rewriting, clears
``editor_verdict`` to None so the next Editor iteration treats the new
draft as a fresh review.

State-mutation wiring
---------------------
- ``output_key="draft"`` overwrites ``state["draft"]`` with the LLM's
  revised markdown.
- ``before_agent_callback`` enforces the early-exit programmatically:
  returns a stub Content if either condition fails, which skips the LLM
  call entirely (saves Gemini cost on the no-op path).
- ``after_agent_callback`` clears ``state["editor_verdict"]`` to None so
  the next Editor pass is a fresh review. ``state["human_feedback"]`` is
  intentionally preserved for traceability per DESIGN.md §10 step 5.
"""

from typing import Optional

from google.adk.agents import LlmAgent
from google.adk.agents.callback_context import CallbackContext
from google.genai import types

from shared.prompts import REVISION_WRITER_INSTRUCTION


def _early_exit_if_not_revise(
    callback_context: CallbackContext,
) -> Optional[types.Content]:
    """Skip the LLM unless we have a revise verdict AND non-empty feedback.

    Also defensively skips when ``chosen_release`` is None (the standard
    pipeline-wide early-exit condition for agents downstream of Triage).
    """
    state = callback_context.state
    if state.get("chosen_release") is None:
        return types.Content(parts=[types.Part(
            text="(revision writer skipped — chosen_release is None)"
        )])
    verdict = state.get("editor_verdict")
    feedback = state.get("human_feedback")
    if verdict != "revise" or not feedback:
        return types.Content(parts=[types.Part(
            text="(revision writer skipped — no revise verdict or empty feedback)"
        )])
    return None


def _clear_editor_verdict_for_fresh_review(
    callback_context: CallbackContext,
) -> Optional[types.Content]:
    """Clear ``editor_verdict`` after a real revision pass.

    Only flips it to None when it was ``"revise"`` going in — that means
    the LLM actually ran. If the agent was skipped (verdict was approve/
    reject/timeout, or chosen_release was None), we leave the verdict
    alone so the loop's escalate signal stays consistent.
    """
    state = callback_context.state
    if state.get("editor_verdict") == "revise":
        state["editor_verdict"] = None
    # Preserve human_feedback per DESIGN.md §10 step 5 ("for traceability").
    return None


revision_writer = LlmAgent(
    name="revision_writer",
    model="gemini-3.1-pro-preview",
    instruction=REVISION_WRITER_INSTRUCTION,
    tools=[],
    output_key="draft",
    before_agent_callback=_early_exit_if_not_revise,
    after_agent_callback=_clear_editor_verdict_for_fresh_review,
)
