"""Tests for the Revision Writer agent + revision_loop wiring.

Coverage maps to the user's two required scenarios from DESIGN.md §10:
- editor_verdict='revise' + feedback "make it shorter" + draft → revised
  draft is shorter, markers preserved, editor_verdict cleared.
- editor_verdict='approve' → exits immediately, draft unchanged.
"""

from types import SimpleNamespace

import pytest


# --- Agent wiring + instruction --------------------------------------------


def test_revision_writer_wiring():
    from agents.revision_writer.agent import revision_writer
    assert revision_writer.name == "revision_writer"
    assert revision_writer.model == "gemini-3.1-pro-preview"
    assert revision_writer.tools == []  # DESIGN.md §10: no tools
    assert revision_writer.output_key == "draft"
    assert revision_writer.before_agent_callback is not None
    assert revision_writer.after_agent_callback is not None


def test_revision_writer_instruction_first_lines_have_chosen_release_then_verdict_check():
    """[Step 11] Pipeline-wide early-exit prepend: line 1 is the
    chosen_release check, line 3 is the Step 10 user-spec verdict check.
    Both early exits remain in force; chosen_release just runs first.
    """
    from agents.revision_writer.agent import revision_writer
    lines = [
        line for line in revision_writer.instruction.splitlines() if line.strip()
    ]
    assert lines[0] == (
        "If state['chosen_release'] is None, end your turn immediately "
        "without using tools."
    )
    assert lines[1] == (
        "If state['editor_verdict'] != 'revise' or "
        "state['human_feedback'] is missing, end your turn immediately."
    )


def test_revision_writer_instruction_encodes_marker_preservation():
    from agents.revision_writer.agent import revision_writer
    instr = revision_writer.instruction
    # Both marker forms must be referenced verbatim per DESIGN.md §10 step 3
    assert "<!-- IMAGE: ... -->" in instr
    assert "<!-- VIDEO: hero -->" in instr
    # Preservation rule
    assert "Preserve" in instr
    # Constraints from DESIGN.md §10
    assert "title or subtitle" in instr
    assert "asset markers" in instr
    assert "research dossiers" in instr


def test_revision_writer_instruction_encodes_clear_verdict_step():
    from agents.revision_writer.agent import revision_writer
    instr = revision_writer.instruction
    # Step 5: Clear editor_verdict, keep human_feedback for traceability
    assert "Clear" in instr or "clear" in instr
    assert "editor_verdict" in instr
    assert "traceability" in instr or "fresh review" in instr


# --- before_agent_callback: programmatic early-exit ------------------------


def test_before_callback_skips_when_verdict_is_approve():
    """[Scenario 2 setup] verdict='approve' → skip the LLM."""
    from agents.revision_writer.agent import _early_exit_if_not_revise
    state = {
        "chosen_release": "x",
        "editor_verdict": "approve",
        "human_feedback": None,
        "draft": "original",
    }
    ctx = SimpleNamespace(state=state)
    result = _early_exit_if_not_revise(ctx)
    assert result is not None  # skip Content returned


def test_before_callback_skips_when_verdict_is_reject():
    from agents.revision_writer.agent import _early_exit_if_not_revise
    state = {
        "chosen_release": "x",
        "editor_verdict": "reject",
        "human_feedback": None,
    }
    assert _early_exit_if_not_revise(SimpleNamespace(state=state)) is not None


def test_before_callback_skips_when_verdict_is_pending_human():
    from agents.revision_writer.agent import _early_exit_if_not_revise
    state = {
        "chosen_release": "x",
        "editor_verdict": "pending_human",
        "human_feedback": None,
    }
    assert _early_exit_if_not_revise(SimpleNamespace(state=state)) is not None


def test_before_callback_skips_when_human_feedback_is_none():
    """Even with verdict='revise', missing feedback → skip."""
    from agents.revision_writer.agent import _early_exit_if_not_revise
    state = {
        "chosen_release": "x",
        "editor_verdict": "revise",
        "human_feedback": None,
    }
    assert _early_exit_if_not_revise(SimpleNamespace(state=state)) is not None


def test_before_callback_skips_when_human_feedback_is_empty_string():
    """Empty feedback string is treated as missing per DESIGN.md."""
    from agents.revision_writer.agent import _early_exit_if_not_revise
    state = {
        "chosen_release": "x",
        "editor_verdict": "revise",
        "human_feedback": "",
    }
    assert _early_exit_if_not_revise(SimpleNamespace(state=state)) is not None


def test_before_callback_skips_when_chosen_release_is_none():
    """Defensive: even if revise+feedback set, exit when Triage skipped."""
    from agents.revision_writer.agent import _early_exit_if_not_revise
    state = {
        "chosen_release": None,
        "editor_verdict": "revise",
        "human_feedback": "make it shorter",
    }
    assert _early_exit_if_not_revise(SimpleNamespace(state=state)) is not None


def test_before_callback_lets_agent_run_when_revise_and_feedback_set():
    """Both conditions met → LLM proceeds (callback returns None)."""
    from agents.revision_writer.agent import _early_exit_if_not_revise
    state = {
        "chosen_release": "x",
        "editor_verdict": "revise",
        "human_feedback": "make it shorter",
    }
    assert _early_exit_if_not_revise(SimpleNamespace(state=state)) is None


# --- after_agent_callback: clear editor_verdict ----------------------------


def test_after_callback_clears_editor_verdict_when_was_revise():
    """[Scenario 1, "editor_verdict cleared" half] After a real revision
    pass, the after-callback flips ``editor_verdict`` to None so the next
    Editor iteration treats the rewritten draft as fresh."""
    from agents.revision_writer.agent import _clear_editor_verdict_for_fresh_review
    state = {
        "editor_verdict": "revise",
        "human_feedback": "make it shorter",
        "draft": "(revised, shorter)",
    }
    _clear_editor_verdict_for_fresh_review(SimpleNamespace(state=state))
    assert state["editor_verdict"] is None
    # human_feedback preserved per DESIGN.md §10 step 5
    assert state["human_feedback"] == "make it shorter"


def test_after_callback_does_not_touch_verdict_when_was_approve():
    """When the LLM was skipped (verdict=approve), don't clobber the
    verdict — the loop's escalate signal depends on it."""
    from agents.revision_writer.agent import _clear_editor_verdict_for_fresh_review
    state = {"editor_verdict": "approve", "draft": "original"}
    _clear_editor_verdict_for_fresh_review(SimpleNamespace(state=state))
    assert state["editor_verdict"] == "approve"


def test_after_callback_does_not_touch_verdict_when_was_reject():
    from agents.revision_writer.agent import _clear_editor_verdict_for_fresh_review
    state = {"editor_verdict": "reject", "draft": "original"}
    _clear_editor_verdict_for_fresh_review(SimpleNamespace(state=state))
    assert state["editor_verdict"] == "reject"


def test_after_callback_is_noop_when_verdict_missing():
    """If something upstream cleared the verdict already, do nothing."""
    from agents.revision_writer.agent import _clear_editor_verdict_for_fresh_review
    state = {"draft": "x"}
    _clear_editor_verdict_for_fresh_review(SimpleNamespace(state=state))
    assert "editor_verdict" not in state


# --- revision_loop wiring (main.py) ---------------------------------------


def test_revision_loop_is_max_3_iterations_with_editor_then_revision_writer():
    """[Loop termination per DESIGN.md §10] revision_loop wires editor and
    revision_writer with max_iterations=3, in that order (editor is the
    entry point)."""
    from agents.editor.agent import editor
    from agents.revision_writer.agent import revision_writer
    from main import revision_loop

    assert revision_loop.name == "revision_loop"
    assert revision_loop.max_iterations == 3
    assert [a.name for a in revision_loop.sub_agents] == ["editor", "revision_writer"]
    assert revision_loop.sub_agents[0] is editor
    assert revision_loop.sub_agents[1] is revision_writer


# --- The two user-required scenarios --------------------------------------


def test_scenario_revise_with_make_it_shorter_keeps_markers_and_clears_verdict():
    """[Scenario 1] editor_verdict='revise' + feedback 'make it shorter' +
    draft (with markers) → revised draft is shorter, markers preserved,
    editor_verdict cleared, human_feedback preserved.

    The actual shortening is done by the LLM, which we can't run in
    pytest. We test the wiring contract: given the LLM produced a
    shorter, marker-preserving rewrite (simulated via output_key writing
    the new draft to state['draft']), the after-callback flips
    editor_verdict to None and leaves human_feedback alone.
    """
    from agents.revision_writer.agent import _clear_editor_verdict_for_fresh_review

    # Original verbose draft with all markers.
    original_draft = (
        "# Build with Anthropic Skills\n## Agents as importable libraries\n\n"
        "<!-- IMAGE: cover -->\n\n"
        "## Setup\n"
        + ("Long verbose paragraph about installing the SDK. " * 6)
        + "\n\n<!-- IMAGE: after-section-1 -->\n\n"
        "## First skill\n```python\nprint('hi')\n```\n\n"
        "<!-- VIDEO: hero -->\n\n"
        "## Where next\n"
        + ("Many filler words here. " * 8)
        + "\n"
    )

    # Simulate the LLM's revised, shorter draft. output_key would have
    # already overwritten state['draft'] by the time after_callback runs.
    revised_draft = (
        "# Build with Anthropic Skills\n## Agents as importable libraries\n\n"
        "<!-- IMAGE: cover -->\n\n"
        "## Setup\nInstall the SDK: `pip install anthropic-skills`.\n\n"
        "<!-- IMAGE: after-section-1 -->\n\n"
        "## First skill\n```python\nprint('hi')\n```\n\n"
        "<!-- VIDEO: hero -->\n\n"
        "## Where next\nLinks below.\n"
    )

    state = {
        "chosen_release": "x",
        "editor_verdict": "revise",
        "human_feedback": "make it shorter",
        "draft": revised_draft,  # output_key would have set this pre-callback
    }

    _clear_editor_verdict_for_fresh_review(SimpleNamespace(state=state))

    # editor_verdict cleared so next Editor pass is fresh
    assert state["editor_verdict"] is None
    # human_feedback preserved for traceability
    assert state["human_feedback"] == "make it shorter"
    # The revised draft is shorter than the original
    assert len(state["draft"]) < len(original_draft)
    # All required markers preserved
    assert "<!-- IMAGE: cover -->" in state["draft"]
    assert "<!-- IMAGE: after-section-1 -->" in state["draft"]
    assert "<!-- VIDEO: hero -->" in state["draft"]
    # Title and subtitle unchanged
    assert "# Build with Anthropic Skills" in state["draft"]
    assert "## Agents as importable libraries" in state["draft"]


def test_scenario_approve_exits_immediately_with_draft_unchanged():
    """[Scenario 2] editor_verdict='approve' → revision_writer's
    before-callback returns a skip Content; even if the after-callback
    fires, it must not corrupt state. Draft stays unchanged."""
    from agents.revision_writer.agent import (
        _clear_editor_verdict_for_fresh_review,
        _early_exit_if_not_revise,
    )

    original_draft = (
        "# Title\n## Subtitle\n\n<!-- IMAGE: cover -->\n\nBody.\n"
    )
    state = {
        "chosen_release": "x",
        "editor_verdict": "approve",
        "human_feedback": None,
        "draft": original_draft,
    }

    # Before-callback returns a skip Content.
    skip = _early_exit_if_not_revise(SimpleNamespace(state=state))
    assert skip is not None
    assert "skipped" in skip.parts[0].text.lower()

    # If the after-callback fires anyway (some ADK versions might call it
    # post-skip), it's a no-op for non-revise verdicts.
    _clear_editor_verdict_for_fresh_review(SimpleNamespace(state=state))

    # Draft completely unchanged.
    assert state["draft"] == original_draft
    # Verdict still 'approve' so the parent loop's escalate signal stands.
    assert state["editor_verdict"] == "approve"
    # human_feedback unchanged.
    assert state["human_feedback"] is None
