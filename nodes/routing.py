"""All 5 routing function nodes for v2. See DESIGN.v2.md §6.

Routing nodes set ``ctx.route = "BRANCH"`` so the dict-edge in agent.py
selects the next node. Returning ``Event(output=...)`` alone does NOT
trigger conditional routing — spike test #1 surfaced this.
"""

from google.adk import Context, Event


# Iteration caps (referenced by route_critic_verdict and record_editor_verdict)
MAX_WRITER_ITERATIONS = 3
MAX_EDITOR_ITERATIONS = 3


def route_after_triage(node_input, ctx: Context) -> Event:
    """§6.2.2 — SKIP if Triage wrote no chosen_release; else CONTINUE."""
    if ctx.state.get("chosen_release") is None:
        ctx.route = "SKIP"
        return Event(output={"route": "SKIP", "reason": ctx.state.get("skip_reason")})
    ctx.route = "CONTINUE"
    return Event(output={"route": "CONTINUE", "title": ctx.state["chosen_release"]["title"]})


def route_topic_verdict(node_input, ctx: Context) -> Event:
    """§6.3.3 — emit ctx.route ∈ {approve, skip, timeout} from topic_verdict."""
    decision = ctx.state["topic_verdict"].verdict
    ctx.route = decision
    return Event(output={"route": decision})


def route_critic_verdict(node_input, ctx: Context) -> Event:
    """§6.6.4 — REVISE/ACCEPT, forced ACCEPT at writer_iterations >= cap."""
    iteration = ctx.state.get("writer_iterations", 0)
    verdict = ctx.state["draft"].critic_verdict
    if iteration >= MAX_WRITER_ITERATIONS:
        ctx.route = "ACCEPT"
        return Event(output={"route": "ACCEPT", "forced": True, "iteration": iteration})
    ctx.route = "ACCEPT" if verdict == "accept" else "REVISE"
    return Event(output={"route": ctx.route, "forced": False, "iteration": iteration})


def route_needs_repo(node_input, ctx: Context) -> Event:
    """§6.8.1 — WITH_REPO if needs_repo=True, else WITHOUT_REPO."""
    needs = bool(ctx.state.get("needs_repo", False))
    ctx.route = "WITH_REPO" if needs else "WITHOUT_REPO"
    return Event(output={"route": ctx.route, "needs_repo": needs})


def route_editor_verdict(node_input, ctx: Context) -> Event:
    """§6.9.3 — emit ctx.route ∈ {approve, reject, revise, timeout}."""
    decision = ctx.state["editor_verdict"].verdict
    ctx.route = decision
    return Event(output={"route": decision})
