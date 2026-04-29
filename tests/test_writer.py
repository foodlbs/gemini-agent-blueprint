"""Tests for the Writer loop: drafter, critic, and the LoopAgent wiring.

Coverage maps to the user's three required scenarios from DESIGN.md §6:
- Simple outline + briefs → draft produced with markers (drafter contract +
  marker checker on a representative draft).
- Loop terminates on accept (set_verdict_accept escalates).
- Stops at iter 3 without accept (LoopAgent max_iterations=3 wired).
"""

from types import SimpleNamespace

import pytest
from google.adk.code_executors import BuiltInCodeExecutor
from google.adk.events import EventActions

from agents.writer.critic import (
    check_markers,
    critic,
    set_verdict_accept,
    set_verdict_revise,
)
from agents.writer.drafter import drafter


# --- check_markers ---------------------------------------------------------


def _ctx(state: dict, *, actions: EventActions | None = None) -> SimpleNamespace:
    """Minimal ToolContext stand-in carrying state and actions."""
    return SimpleNamespace(state=state, actions=actions or EventActions())


def test_check_markers_passes_when_all_image_and_video_markers_present():
    state = {
        "draft": (
            "# Title\n<!-- IMAGE: cover -->\n## Setup\nWords.\n"
            "<!-- IMAGE: after-section-1 -->\n```python\nprint('hi')\n```\n"
            "<!-- VIDEO: hero -->\nMore words."
        ),
        "image_brief": [
            {"position": "cover"},
            {"position": "after-section-1"},
        ],
        "needs_video": True,
    }
    result = check_markers(_ctx(state))
    assert result["all_markers_present"] is True
    assert result["missing_image_positions"] == []
    assert result["missing_video"] is False


def test_check_markers_reports_missing_image_position():
    state = {
        "draft": "# Title\n<!-- IMAGE: cover -->\nbody",
        "image_brief": [
            {"position": "cover"},
            {"position": "after-section-1"},
        ],
        "needs_video": False,
    }
    result = check_markers(_ctx(state))
    assert result["all_markers_present"] is False
    assert result["missing_image_positions"] == ["after-section-1"]
    assert result["missing_video"] is False


def test_check_markers_reports_missing_video_when_needs_video_true():
    state = {
        "draft": "# Title\n<!-- IMAGE: cover -->\nbody",
        "image_brief": [{"position": "cover"}],
        "needs_video": True,
    }
    result = check_markers(_ctx(state))
    assert result["all_markers_present"] is False
    assert result["missing_video"] is True


def test_check_markers_ignores_video_marker_when_needs_video_false():
    state = {
        "draft": "# Title\n<!-- IMAGE: cover -->\nbody",
        "image_brief": [{"position": "cover"}],
        "needs_video": False,
    }
    result = check_markers(_ctx(state))
    assert result["all_markers_present"] is True
    assert result["missing_video"] is False


def test_check_markers_handles_empty_image_brief_and_no_video():
    state = {"draft": "# Title only.", "image_brief": [], "needs_video": False}
    result = check_markers(_ctx(state))
    assert result["all_markers_present"] is True


# --- set_verdict_accept / set_verdict_revise -------------------------------


def test_set_verdict_accept_escalates_and_records_verdict():
    state = {"critic_feedback": "old feedback"}
    actions = EventActions()
    ctx = _ctx(state, actions=actions)

    out = set_verdict_accept(ctx)

    assert state["critic_verdict"] == "accept"
    # Stale feedback from a prior iteration should be cleared on accept.
    assert "critic_feedback" not in state
    # The contract that breaks the LoopAgent:
    assert actions.escalate is True
    assert "accept" in out.lower()


def test_set_verdict_revise_records_feedback_without_escalating():
    state = {}
    actions = EventActions()
    ctx = _ctx(state, actions=actions)

    out = set_verdict_revise("rewrite the intro to hook in 50 words", ctx)

    assert state["critic_verdict"] == "revise"
    assert state["critic_feedback"] == "rewrite the intro to hook in 50 words"
    # Critically, do NOT escalate on revise — the loop must continue.
    assert actions.escalate is None or actions.escalate is False
    assert "revis" in out.lower()


# --- Drafter wiring + instruction --------------------------------------------


def test_drafter_wiring():
    assert drafter.name == "drafter"
    assert drafter.model == "gemini-3.1-pro-preview"
    assert drafter.tools == []
    assert drafter.output_key == "draft"


def test_drafter_instruction_first_line_is_early_exit():
    first_line = drafter.instruction.splitlines()[0]
    assert first_line == (
        "If state['chosen_release'] is None, end your turn immediately without using tools."
    )


def test_drafter_instruction_encodes_marker_insertion():
    instr = drafter.instruction
    # Both marker formats must be in the instruction verbatim so the LLM
    # produces them in the exact form check_markers looks for.
    assert "<!-- IMAGE: <position> -->" in instr
    assert "<!-- VIDEO: hero -->" in instr
    assert "image_brief" in instr
    assert "needs_video" in instr
    # Quote-budget rule per DESIGN.md §6a.
    assert "≤14 words" in instr or "14 words" in instr


# --- Critic wiring + instruction ---------------------------------------------


def test_critic_wiring():
    assert critic.name == "critic"
    assert critic.model == "gemini-3.1-pro-preview"
    assert isinstance(critic.code_executor, BuiltInCodeExecutor)
    tool_names = {getattr(t, "__name__", str(t)) for t in critic.tools}
    assert tool_names == {"check_markers", "set_verdict_accept", "set_verdict_revise"}


def test_critic_instruction_first_line_is_early_exit():
    first_line = critic.instruction.splitlines()[0]
    assert first_line == (
        "If state['chosen_release'] is None, end your turn immediately without using tools."
    )


def test_critic_instruction_encodes_scoring_rules():
    instr = critic.instruction
    # Five axes from DESIGN.md §6b
    for axis in ("accuracy", "code-correctness", "originality", "copyright safety", "reader value"):
        assert axis in instr
    # Total threshold and per-axis floor
    assert "22" in instr
    assert "4" in instr
    # Verdict tools the LLM must call
    assert "set_verdict_accept" in instr
    assert "set_verdict_revise" in instr
    assert "check_markers" in instr


# --- writer_loop composition -----------------------------------------------


def test_writer_loop_is_max_3_iterations_with_drafter_then_critic():
    """[User-required scenario 3] Loop stops at iter 3 without accept —
    verified by max_iterations=3 wiring."""
    from main import writer_loop

    assert writer_loop.name == "writer_loop"
    assert writer_loop.max_iterations == 3
    # Order matters: drafter writes, critic reads. Reversed would be a bug.
    assert [a.name for a in writer_loop.sub_agents] == ["drafter", "critic"]
    assert writer_loop.sub_agents[0] is drafter
    assert writer_loop.sub_agents[1] is critic


# --- The three user-required scenarios -------------------------------------


def test_simple_outline_and_briefs_yield_draft_with_markers():
    """[Scenario 1] Simple outline + briefs → the drafter is committed to
    inserting the right markers, and a representative draft passes the
    Critic's marker check.

    We can't run the LLM in pytest. We assert (a) the drafter's instruction
    requires the markers (instruction-as-contract), and (b) a hand-crafted
    draft of the expected shape passes ``check_markers`` with the same
    briefs. Together these lock down the producer-consumer contract.
    """
    image_brief = [
        {"position": "cover"},
        {"position": "after-section-1"},
        {"position": "after-section-2"},
    ]
    needs_video = True

    # (a) Instruction encodes the marker rule (already covered by
    # test_drafter_instruction_encodes_marker_insertion; re-asserted briefly):
    assert "<!-- IMAGE: <position> -->" in drafter.instruction
    assert "<!-- VIDEO: hero -->" in drafter.instruction

    # (b) A draft shaped like the LLM's expected output passes the check.
    expected_draft = (
        "# Working Title\n## Working subtitle\n\n"
        "<!-- IMAGE: cover -->\n\n"
        "## Setup\nInstall the SDK.\n\n"
        "<!-- IMAGE: after-section-1 -->\n\n"
        "## First skill\n```python\nprint('hello')\n```\n\n"
        "<!-- VIDEO: hero -->\n\n"
        "## Where next\nLinks.\n\n"
        "<!-- IMAGE: after-section-2 -->\n"
    )
    state = {
        "draft": expected_draft,
        "image_brief": image_brief,
        "needs_video": needs_video,
    }
    result = check_markers(_ctx(state))
    assert result["all_markers_present"] is True


def test_loop_terminates_on_accept_via_escalate():
    """[Scenario 2] Loop terminates when the critic accepts.

    The critic's accept path: call ``set_verdict_accept`` → the tool sets
    ``actions.escalate = True``. ``LoopAgent`` reads ``escalate`` after each
    sub-agent finishes and breaks the loop when it sees True. We test the
    contract by exercising the tool and asserting the escalate flag.
    """
    state = {}
    actions = EventActions()
    ctx = _ctx(state, actions=actions)

    set_verdict_accept(ctx)

    assert state["critic_verdict"] == "accept"
    assert actions.escalate is True


def test_loop_continues_on_revise_without_escalate():
    """Counterpart to scenario 2: revise does NOT escalate, so the loop
    runs another iteration (or hits max_iterations=3)."""
    state = {}
    actions = EventActions()
    ctx = _ctx(state, actions=actions)

    set_verdict_revise("tighten section 2", ctx)

    assert state["critic_verdict"] == "revise"
    assert state["critic_feedback"] == "tighten section 2"
    # Loop continues — escalate must not be True.
    assert actions.escalate is not True
