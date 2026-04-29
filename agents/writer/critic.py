"""Critic — scores the draft and decides accept/revise.

DESIGN.md §6b: Gemini 3.1 Pro with ADK Code Execution. Uses three function
tools to drive the writer loop:

- ``check_markers`` — verifies image/video markers are present in the draft.
- ``set_verdict_accept`` — records the accept verdict AND sets
  ``tool_context.actions.escalate = True`` so the parent ``LoopAgent`` exits.
- ``set_verdict_revise`` — records a revise verdict + actionable feedback so
  the next loop iteration's Drafter can rewrite.

Code execution is wired via ``code_executor=BuiltInCodeExecutor()``; the
critic actually runs Python blocks from the draft when scoring code-correctness.
"""

from google.adk.agents import LlmAgent
from google.adk.code_executors import BuiltInCodeExecutor
from google.adk.tools.tool_context import ToolContext

from shared.prompts import CRITIC_INSTRUCTION


def check_markers(tool_context: ToolContext) -> dict:
    """Verify required ``<!-- IMAGE: ... -->`` and ``<!-- VIDEO: hero -->``
    markers are present in ``state["draft"]``.

    The Drafter is required to insert one ``<!-- IMAGE: <position> -->`` for
    every entry in ``state["image_brief"]``, plus ``<!-- VIDEO: hero -->``
    when ``state["needs_video"]`` is True. The Critic calls this tool first;
    if anything is missing it must immediately request a revision.

    Returns:
        dict with:
        - ``missing_image_positions``: list of positions whose marker is absent.
        - ``missing_video``: bool — True if ``needs_video`` is True and the
          video marker is absent.
        - ``all_markers_present``: bool — True iff nothing is missing.
    """
    state = tool_context.state
    draft = state.get("draft", "") or ""
    image_brief = state.get("image_brief", []) or []
    needs_video = bool(state.get("needs_video", False))

    missing_image_positions: list[str] = []
    for spec in image_brief:
        if isinstance(spec, dict):
            position = spec.get("position")
        else:
            position = getattr(spec, "position", None)
        if position and f"<!-- IMAGE: {position} -->" not in draft:
            missing_image_positions.append(position)

    missing_video = needs_video and "<!-- VIDEO: hero -->" not in draft

    return {
        "missing_image_positions": missing_image_positions,
        "missing_video": missing_video,
        "all_markers_present": (not missing_image_positions) and (not missing_video),
    }


def set_verdict_accept(tool_context: ToolContext) -> str:
    """Mark the draft accepted and escalate to terminate the writer loop.

    Setting ``tool_context.actions.escalate = True`` is ADK's documented
    mechanism for breaking out of a parent ``LoopAgent`` early.
    """
    tool_context.state["critic_verdict"] = "accept"
    tool_context.state.pop("critic_feedback", None)
    tool_context.actions.escalate = True
    return "draft accepted"


def set_verdict_revise(feedback: str, tool_context: ToolContext) -> str:
    """Record a revise verdict with concrete, actionable feedback.

    Args:
        feedback: Specific revision notes for the Drafter. Will be read
            from ``state["critic_feedback"]`` on the next loop iteration.
    """
    tool_context.state["critic_verdict"] = "revise"
    tool_context.state["critic_feedback"] = feedback
    return "revision requested"


critic = LlmAgent(
    name="critic",
    model="gemini-3.1-pro-preview",
    instruction=CRITIC_INSTRUCTION,
    tools=[check_markers, set_verdict_accept, set_verdict_revise],
    code_executor=BuiltInCodeExecutor(),
)
