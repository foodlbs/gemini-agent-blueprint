"""Regression guard — fail the build if the workflow graph contains an
implicit fan-in (a node with multiple unconditional incoming edges that
isn't a JoinFunctionNode).

See docs/superpowers/specs/2026-05-01-fan-in-join-design.md for why this
matters: a plain FunctionNode with multiple unconditional incoming edges
re-fires its entire downstream chain once per predecessor, producing
duplicate side-effects (e.g., 3 editor Telegram messages per cycle)."""

from collections import defaultdict

from agent import root_agent
from nodes._join_node import JoinFunctionNode


# Nodes with multiple unconditional incoming edges that are NOT bugs.
# Each entry maps node-name → reason. Adding here is a deliberate choice:
# the audit must show the convergence is safe (mutually exclusive at
# runtime), not just convenient. See the spec's "Audit correction"
# section for the analysis pattern.
KNOWN_SAFE_FAN_IN: dict[str, str] = {
    "editor_request": (
        "Two unconditional incoming edges (repo_builder, revision_writer) "
        "are mutually exclusive at runtime. repo_builder fires once on "
        "initial WITH_REPO traversal; revision_writer fires sequentially "
        "after a 'revise' verdict on the previously-resolved editor_request. "
        "They never fire concurrently. See "
        "docs/superpowers/specs/2026-05-01-fan-in-join-design.md "
        "(Audit correction section)."
    ),
}


def test_no_implicit_fan_in_in_root_agent():
    """Every node in root_agent.graph with > 1 unconditional incoming edge
    must be either a JoinFunctionNode or in KNOWN_SAFE_FAN_IN."""
    assert root_agent.graph is not None, "root_agent.graph not built"

    unconditional_in_count: dict[str, int] = defaultdict(int)
    for edge in root_agent.graph.edges:
        if edge.route is None:
            unconditional_in_count[edge.to_node.name] += 1

    nodes_by_name = {n.name: n for n in root_agent.graph.nodes}

    offenders = []
    for name, count in unconditional_in_count.items():
        if count <= 1:
            continue
        if name in KNOWN_SAFE_FAN_IN:
            continue  # Documented exemption.
        node = nodes_by_name[name]
        if not isinstance(node, JoinFunctionNode):
            offenders.append(
                f"{name!r}: {count} unconditional incoming edges, but is "
                f"{type(node).__name__} (must be JoinFunctionNode or added "
                f"to KNOWN_SAFE_FAN_IN with a documented reason)"
            )

    assert not offenders, (
        "Implicit fan-in detected — these nodes have multiple unconditional "
        "incoming edges but are not JoinFunctionNode instances. They will "
        "re-fire downstream once per predecessor. Either reduce the incoming "
        "edges to 1, refactor as a JoinFunctionNode, or add to "
        "KNOWN_SAFE_FAN_IN with a documented reason. See "
        "docs/superpowers/specs/2026-05-01-fan-in-join-design.md.\n  - "
        + "\n  - ".join(offenders)
    )
