"""Unit tests for nodes/routing.py — the 5 routing function nodes.

Each routing node is total: reads state, sets ctx.route, returns Event.
Tests use a MagicMock for ctx (dict-like .state, settable .route).
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

from nodes.routing import (
    MAX_EDITOR_ITERATIONS,
    MAX_WRITER_ITERATIONS,
    route_after_triage,
    route_critic_verdict,
    route_editor_verdict,
    route_needs_repo,
    route_topic_verdict,
)


def _ctx(state: dict) -> MagicMock:
    """A minimal ctx — .state is a real dict, .route is set by the node."""
    ctx = MagicMock()
    ctx.state = state
    ctx.route = None
    return ctx


# --- route_after_triage ----------------------------------------------------


def test_route_after_triage_emits_SKIP_when_chosen_release_is_None():
    ctx = _ctx({"chosen_release": None, "skip_reason": "nothing met bar"})
    event = route_after_triage(None, ctx)
    assert ctx.route == "SKIP"
    assert event.output["route"] == "SKIP"
    assert event.output["reason"] == "nothing met bar"


def test_route_after_triage_emits_CONTINUE_when_chosen_release_set():
    ctx = _ctx({
        "chosen_release": {"title": "Anthropic Skills SDK", "url": "https://x"},
    })
    event = route_after_triage(None, ctx)
    assert ctx.route == "CONTINUE"
    assert event.output["route"] == "CONTINUE"
    assert event.output["title"] == "Anthropic Skills SDK"


def test_route_after_triage_handles_missing_chosen_release_key():
    """Defensive — state without the key (shouldn't happen) is treated as SKIP."""
    ctx = _ctx({})
    event = route_after_triage(None, ctx)
    assert ctx.route == "SKIP"


# --- route_topic_verdict ---------------------------------------------------


def test_route_topic_verdict_approve():
    ctx = _ctx({"topic_verdict": SimpleNamespace(verdict="approve")})
    route_topic_verdict(None, ctx)
    assert ctx.route == "approve"


def test_route_topic_verdict_skip():
    ctx = _ctx({"topic_verdict": SimpleNamespace(verdict="skip")})
    route_topic_verdict(None, ctx)
    assert ctx.route == "skip"


def test_route_topic_verdict_timeout():
    ctx = _ctx({"topic_verdict": SimpleNamespace(verdict="timeout")})
    route_topic_verdict(None, ctx)
    assert ctx.route == "timeout"


# --- route_critic_verdict --------------------------------------------------


def test_route_critic_verdict_REVISE_when_critic_says_revise_below_cap():
    ctx = _ctx({
        "draft": SimpleNamespace(critic_verdict="revise"),
        "writer_iterations": 1,
    })
    event = route_critic_verdict(None, ctx)
    assert ctx.route == "REVISE"
    assert event.output["forced"] is False


def test_route_critic_verdict_ACCEPT_when_critic_says_accept_below_cap():
    ctx = _ctx({
        "draft": SimpleNamespace(critic_verdict="accept"),
        "writer_iterations": 1,
    })
    event = route_critic_verdict(None, ctx)
    assert ctx.route == "ACCEPT"
    assert event.output["forced"] is False


def test_route_critic_verdict_FORCES_ACCEPT_at_cap_even_if_revise():
    """Bug-prevention: infinite writer loop is impossible."""
    ctx = _ctx({
        "draft": SimpleNamespace(critic_verdict="revise"),
        "writer_iterations": MAX_WRITER_ITERATIONS,
    })
    event = route_critic_verdict(None, ctx)
    assert ctx.route == "ACCEPT"
    assert event.output["forced"] is True
    assert event.output["iteration"] == MAX_WRITER_ITERATIONS


def test_route_critic_verdict_forces_ACCEPT_above_cap_too():
    """Defensive — should never reach iteration > cap, but test confirms."""
    ctx = _ctx({
        "draft": SimpleNamespace(critic_verdict="revise"),
        "writer_iterations": MAX_WRITER_ITERATIONS + 5,
    })
    event = route_critic_verdict(None, ctx)
    assert ctx.route == "ACCEPT"
    assert event.output["forced"] is True


# --- route_needs_repo ------------------------------------------------------


def test_route_needs_repo_WITH_REPO():
    ctx = _ctx({"needs_repo": True})
    event = route_needs_repo(None, ctx)
    assert ctx.route == "WITH_REPO"
    assert event.output["needs_repo"] is True


def test_route_needs_repo_WITHOUT_REPO():
    ctx = _ctx({"needs_repo": False})
    event = route_needs_repo(None, ctx)
    assert ctx.route == "WITHOUT_REPO"
    assert event.output["needs_repo"] is False


def test_route_needs_repo_WITHOUT_REPO_when_key_missing():
    """Defensive — default Pydantic state has needs_repo=False."""
    ctx = _ctx({})
    event = route_needs_repo(None, ctx)
    assert ctx.route == "WITHOUT_REPO"


# --- route_editor_verdict --------------------------------------------------


def test_route_editor_verdict_each_branch():
    """One assertion per branch — 4 branches in the dict-edge."""
    for verdict in ("approve", "reject", "revise", "timeout"):
        ctx = _ctx({"editor_verdict": SimpleNamespace(verdict=verdict)})
        route_editor_verdict(None, ctx)
        assert ctx.route == verdict, f"failed for verdict={verdict}"


# --- Iteration cap constants ----------------------------------------------


def test_iteration_caps_match_design():
    """DESIGN.v2.md §6.6.4 + §6.9.2 specify 3 iterations max for both loops."""
    assert MAX_WRITER_ITERATIONS == 3
    assert MAX_EDITOR_ITERATIONS == 3
