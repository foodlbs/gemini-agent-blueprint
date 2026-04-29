"""Unit tests for nodes/records.py — verdict recorders + 5 terminal nodes.

Per DESIGN.v2.md §6.2.3, §6.3.2, §6.3.4, §6.3.5, §6.9.2, §6.9.4, §6.9.5.
"""

from unittest.mock import MagicMock, patch

from nodes.records import (
    MAX_EDITOR_ITERATIONS,
    _coerce_editor_response,
    _coerce_topic_decision,
    record_editor_rejection,
    record_editor_timeout,
    record_editor_verdict,
    record_human_topic_skip,
    record_topic_timeout,
    record_topic_verdict,
    record_triage_skip,
)


def _ctx(state: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.state = state
    return ctx


# --- _coerce_topic_decision ------------------------------------------------


def test_coerce_topic_decision_dict_approve():
    assert _coerce_topic_decision({"decision": "approve"}) == "approve"


def test_coerce_topic_decision_dict_skip():
    assert _coerce_topic_decision({"decision": "skip"}) == "skip"


def test_coerce_topic_decision_string_approve():
    assert _coerce_topic_decision("approve") == "approve"


def test_coerce_topic_decision_unknown_falls_back_to_timeout():
    assert _coerce_topic_decision({"decision": "garbage"}) == "timeout"
    assert _coerce_topic_decision({"unrelated_key": "x"}) == "timeout"


# --- _coerce_editor_response -----------------------------------------------


def test_coerce_editor_response_revise_with_feedback():
    decision, feedback = _coerce_editor_response({
        "decision": "revise", "feedback": "shorten the intro",
    })
    assert decision == "revise"
    assert feedback == "shorten the intro"


def test_coerce_editor_response_approve_no_feedback():
    decision, feedback = _coerce_editor_response({"decision": "approve"})
    assert decision == "approve"
    assert feedback == ""


def test_coerce_editor_response_unknown_falls_back_to_timeout():
    decision, feedback = _coerce_editor_response({"decision": "yikes"})
    assert decision == "timeout"


# --- record_topic_verdict --------------------------------------------------


def test_record_topic_verdict_approve_does_not_write_memory_bank():
    ctx = _ctx({"chosen_release": {"title": "T", "url": "u", "source": "arxiv"}})
    with patch("tools.memory.memory_bank_add_fact") as mock_add:
        record_topic_verdict({"decision": "approve"}, ctx)
    assert mock_add.call_count == 0
    assert ctx.state["topic_verdict"].verdict == "approve"


def test_record_topic_verdict_skip_writes_human_rejected_to_memory_bank():
    ctx = _ctx({
        "chosen_release": {"title": "T", "url": "https://x", "source": "arxiv"},
    })
    with patch("tools.memory.memory_bank_add_fact") as mock_add:
        record_topic_verdict({"decision": "skip"}, ctx)
    assert mock_add.call_count == 1
    call = mock_add.call_args
    assert call.kwargs["scope"] == "ai_release_pipeline"
    assert call.kwargs["metadata"]["type"] == "human-rejected"
    assert call.kwargs["metadata"]["release_url"] == "https://x"


def test_record_topic_verdict_timeout_does_not_write_memory_bank():
    ctx = _ctx({"chosen_release": {"title": "T", "url": "u", "source": "arxiv"}})
    with patch("tools.memory.memory_bank_add_fact") as mock_add:
        record_topic_verdict({"decision": "timeout"}, ctx)
    assert mock_add.call_count == 0
    assert ctx.state["topic_verdict"].verdict == "timeout"


def test_record_topic_verdict_memory_bank_failure_does_not_raise(caplog):
    """Per §12.3 — Memory Bank write failures must NOT fail the cycle."""
    ctx = _ctx({"chosen_release": {"title": "T", "url": "u", "source": "arxiv"}})
    with patch("tools.memory.memory_bank_add_fact", side_effect=RuntimeError("oops")):
        # Should not raise.
        event = record_topic_verdict({"decision": "skip"}, ctx)
    assert event.output["verdict"] == "skip"


# --- record_triage_skip ----------------------------------------------------


def test_record_triage_skip_sets_cycle_outcome():
    ctx = _ctx({"chosen_release": None, "skip_reason": "no candidates"})
    event = record_triage_skip(None, ctx)
    assert ctx.state["cycle_outcome"] == "skipped_by_triage"
    assert event.output["outcome"] == "skipped_by_triage"


def test_record_triage_skip_logs_when_chosen_release_present(caplog):
    """Defensive — if routing is broken and we got here with chosen_release set,
    log loudly. Cycle outcome still gets set."""
    import logging
    caplog.set_level(logging.ERROR)
    ctx = _ctx({"chosen_release": {"title": "x"}})
    record_triage_skip(None, ctx)
    assert ctx.state["cycle_outcome"] == "skipped_by_triage"
    assert any("routing bug" in r.message for r in caplog.records)


# --- record_human_topic_skip -----------------------------------------------


def test_record_human_topic_skip_sets_cycle_outcome():
    ctx = _ctx({})
    event = record_human_topic_skip(None, ctx)
    assert ctx.state["cycle_outcome"] == "skipped_by_human_topic"
    assert event.output["outcome"] == "skipped_by_human_topic"


# --- record_topic_timeout --------------------------------------------------


def test_record_topic_timeout_clears_chosen_release():
    """Per §6.3.5 — timeout ≠ rejection; future cycles can re-surface."""
    ctx = _ctx({"chosen_release": {"title": "x"}})
    event = record_topic_timeout(None, ctx)
    assert ctx.state["chosen_release"] is None
    assert ctx.state["skip_reason"] == "topic-gate-timeout"
    assert ctx.state["cycle_outcome"] == "topic_timeout"


def test_record_topic_timeout_does_not_write_memory_bank():
    """Per §6.3.5 — timeout writes NO Memory Bank fact."""
    ctx = _ctx({"chosen_release": {"title": "x", "url": "u", "source": "arxiv"}})
    with patch("tools.memory.memory_bank_add_fact") as mock_add:
        record_topic_timeout(None, ctx)
    assert mock_add.call_count == 0


# --- record_editor_verdict -------------------------------------------------


def test_record_editor_verdict_records_approve():
    ctx = _ctx({"editor_iterations": 0})
    event = record_editor_verdict({"decision": "approve"}, ctx)
    assert ctx.state["editor_verdict"].verdict == "approve"
    assert ctx.state["editor_iterations"] == 1
    assert event.output["verdict"] == "approve"


def test_record_editor_verdict_records_reject():
    ctx = _ctx({"editor_iterations": 0})
    event = record_editor_verdict({"decision": "reject"}, ctx)
    assert ctx.state["editor_verdict"].verdict == "reject"


def test_record_editor_verdict_revise_sets_human_feedback():
    ctx = _ctx({"editor_iterations": 0})
    event = record_editor_verdict(
        {"decision": "revise", "feedback": "shorten intro"}, ctx
    )
    assert ctx.state["editor_verdict"].verdict == "revise"
    assert ctx.state["human_feedback"].feedback == "shorten intro"


def test_record_editor_verdict_increments_iterations_each_call():
    ctx = _ctx({"editor_iterations": 2})
    record_editor_verdict({"decision": "approve"}, ctx)
    assert ctx.state["editor_iterations"] == 3


def test_record_editor_verdict_forces_reject_at_iteration_above_cap():
    """Per §6.9.2 — revise at iteration > cap → forced reject + appended note."""
    ctx = _ctx({"editor_iterations": MAX_EDITOR_ITERATIONS})
    event = record_editor_verdict({"decision": "revise", "feedback": "x"}, ctx)
    assert ctx.state["editor_verdict"].verdict == "reject"
    assert "forced reject" in ctx.state["editor_verdict"].feedback
    assert event.output["verdict"] == "reject"


def test_record_editor_verdict_revise_at_cap_minus_one_still_allowed():
    """Boundary — at exactly cap-1, revise should go through."""
    ctx = _ctx({"editor_iterations": MAX_EDITOR_ITERATIONS - 1})
    event = record_editor_verdict({"decision": "revise"}, ctx)
    # editor_iterations becomes cap; verdict stays revise
    assert ctx.state["editor_verdict"].verdict == "revise"
    assert ctx.state["editor_iterations"] == MAX_EDITOR_ITERATIONS


# --- record_editor_rejection -----------------------------------------------


def test_record_editor_rejection_sets_cycle_outcome_no_memory_bank():
    """Per §6.9.4 — Editor reject writes NO Memory Bank fact (release can re-surface)."""
    from datetime import datetime, timezone
    from shared.models import EditorVerdict
    ctx = _ctx({
        "chosen_release": {"title": "x", "url": "u", "source": "arxiv"},
        "editor_verdict": EditorVerdict(verdict="reject", feedback="bad draft", at=datetime.now(timezone.utc)),
    })
    with patch("tools.memory.memory_bank_add_fact") as mock_add:
        event = record_editor_rejection(None, ctx)
    assert ctx.state["cycle_outcome"] == "rejected_by_editor"
    assert mock_add.call_count == 0
    assert event.output["feedback"] == "bad draft"


# --- record_editor_timeout -------------------------------------------------


def test_record_editor_timeout_sets_cycle_outcome():
    ctx = _ctx({})
    event = record_editor_timeout(None, ctx)
    assert ctx.state["cycle_outcome"] == "editor_timeout"
    assert event.output["outcome"] == "editor_timeout"
