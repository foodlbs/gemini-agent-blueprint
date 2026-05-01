"""Unit test for JoinFunctionNode — see
docs/superpowers/specs/2026-05-01-fan-in-join-design.md."""

from google.adk import Context, Event

from nodes._join_node import JoinFunctionNode


def test_join_function_node_defaults_wait_for_output_true():
    """A JoinFunctionNode must have wait_for_output=True so it stays
    WAITING after returning a no-output Event, allowing predecessors
    to re-trigger it. See ADK _base_node.py:65-74 for the contract."""
    def _noop(node_input, ctx: Context) -> Event:
        return Event()

    node = JoinFunctionNode(func=_noop, name="test_join")
    assert node.wait_for_output is True
