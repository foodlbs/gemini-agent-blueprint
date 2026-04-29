"""Verdict-recording + terminal nodes. See DESIGN.v2.md §6.

Two recording nodes (record_topic_verdict, record_editor_verdict) parse
the resume input from a paused HITL node into typed state. Five
terminal nodes (record_*_skip / _rejection / _timeout) each set
`cycle_outcome` so post-cycle reporting knows how the cycle ended.
"""

import logging
from datetime import datetime, timezone

from google.adk import Context, Event

from shared.models import EditorVerdict, RevisionFeedback, TopicVerdict

logger = logging.getLogger(__name__)

# Iteration cap shared with route_critic_verdict (kept here too because
# record_editor_verdict enforces it before the route node runs).
MAX_EDITOR_ITERATIONS = 3


# --- Coercion helpers -------------------------------------------------------


def _coerce_topic_decision(node_input) -> str:
    """Map raw FunctionResponse payload → one of {approve, skip, timeout}."""
    if isinstance(node_input, dict):
        decision = node_input.get("decision", "")
    elif isinstance(node_input, str):
        decision = node_input.lower()
    elif hasattr(node_input, "parts"):  # genai.types.Content
        text = " ".join(
            getattr(p, "text", "") or "" for p in node_input.parts
        ).lower()
        decision = text
    else:
        decision = str(node_input)
    decision = decision.lower().strip()
    if "approve" in decision:
        return "approve"
    if "skip" in decision:
        return "skip"
    return "timeout"


def _coerce_editor_response(node_input) -> tuple[str, str]:
    """Map raw FunctionResponse payload → (decision, feedback)."""
    decision = "timeout"
    feedback = ""
    if isinstance(node_input, dict):
        d = (node_input.get("decision") or "").lower()
        if d in ("approve", "reject", "revise", "timeout"):
            decision = d
        feedback = node_input.get("feedback") or ""
    elif isinstance(node_input, str):
        d = node_input.lower()
        for token in ("approve", "reject", "revise", "timeout"):
            if token in d:
                decision = token
                break
    return decision, feedback


# --- Verdict recorders (HITL #1 + #2) ---------------------------------------


def record_topic_verdict(node_input, ctx: Context) -> Event:
    """§6.3.2 — set topic_verdict; on skip, write Memory Bank human-rejected."""
    decision = _coerce_topic_decision(node_input)
    ctx.state["topic_verdict"] = TopicVerdict(
        verdict=decision, at=datetime.now(timezone.utc)
    )
    if decision == "skip":
        chosen = ctx.state.get("chosen_release") or {}
        try:
            from tools.memory import memory_bank_add_fact
            memory_bank_add_fact(
                scope="ai_release_pipeline",
                fact=f"Human rejected topic: {chosen.get('title', '?')}",
                metadata={
                    "type": "human-rejected",
                    "release_url": chosen.get("url"),
                    "release_source": chosen.get("source"),
                    "rejected_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except ImportError:
            # tools/memory.py not yet implemented (§7.2). Best-effort.
            logger.warning("memory_bank_add_fact unavailable — skip fact not persisted")
        except Exception as e:
            logger.warning("memory_bank_add_fact failed: %s", e)
    return Event(output={"verdict": decision})


def record_editor_verdict(node_input, ctx: Context) -> Event:
    """§6.9.2 — set editor_verdict; enforce iteration cap (force reject at >3)."""
    decision, feedback = _coerce_editor_response(node_input)
    iter_count = ctx.state.get("editor_iterations", 0) + 1

    if iter_count > MAX_EDITOR_ITERATIONS and decision == "revise":
        logger.warning(
            "Editor revise at iteration %d > cap %d — forcing reject.",
            iter_count, MAX_EDITOR_ITERATIONS,
        )
        decision = "reject"
        feedback = (feedback or "") + " [forced reject: revision cap reached]"

    now = datetime.now(timezone.utc)
    ctx.state["editor_verdict"] = EditorVerdict(
        verdict=decision, feedback=feedback, at=now,
    )
    if decision == "revise":
        ctx.state["human_feedback"] = RevisionFeedback(feedback=feedback or "", at=now)
    ctx.state["editor_iterations"] = iter_count
    return Event(output={
        "verdict": decision, "iteration": iter_count, "has_feedback": bool(feedback),
    })


# --- Terminal nodes (set cycle_outcome) -------------------------------------


def record_triage_skip(node_input, ctx: Context) -> Event:
    """§6.2.3 — terminal node when Triage skipped."""
    if ctx.state.get("chosen_release") is not None:
        logger.error(
            "record_triage_skip reached with chosen_release=%r; routing bug",
            ctx.state["chosen_release"],
        )
    ctx.state["cycle_outcome"] = "skipped_by_triage"
    return Event(output={"outcome": "skipped_by_triage", "reason": ctx.state.get("skip_reason")})


def record_human_topic_skip(node_input, ctx: Context) -> Event:
    """§6.3.4 — terminal node when human pressed Skip on Topic Gate."""
    ctx.state["cycle_outcome"] = "skipped_by_human_topic"
    return Event(output={"outcome": "skipped_by_human_topic"})


def record_topic_timeout(node_input, ctx: Context) -> Event:
    """§6.3.5 — terminal node when Topic Gate timed out (sweeper-driven)."""
    ctx.state["chosen_release"] = None
    ctx.state["skip_reason"] = "topic-gate-timeout"
    ctx.state["cycle_outcome"] = "topic_timeout"
    return Event(output={"outcome": "topic_timeout"})


def record_editor_rejection(node_input, ctx: Context) -> Event:
    """§6.9.4 — terminal node when Editor rejected. No Memory Bank fact written."""
    ctx.state["cycle_outcome"] = "rejected_by_editor"
    return Event(output={
        "outcome": "rejected_by_editor",
        "feedback": ctx.state["editor_verdict"].feedback if ctx.state.get("editor_verdict") else None,
    })


def record_editor_timeout(node_input, ctx: Context) -> Event:
    """§6.9.5 — terminal node when Editor timed out (sweeper-driven)."""
    ctx.state["cycle_outcome"] = "editor_timeout"
    return Event(output={"outcome": "editor_timeout"})
