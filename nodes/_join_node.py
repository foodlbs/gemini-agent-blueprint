"""JoinFunctionNode — a FunctionNode preconfigured for graph fan-in joins.

A node with multiple unconditional incoming edges (true fan-in) must use
this subclass instead of a plain function, otherwise each predecessor's
completion independently triggers the function and cascades downstream
once per predecessor (see post-md-inject regression diagnosed in
docs/superpowers/specs/2026-05-01-fan-in-join-design.md).

Mechanism: ADK's `BaseNode.wait_for_output=True` keeps the node in WAITING
state when its function returns an Event with no output, allowing
predecessors to re-trigger it. The function decides when "all inputs
ready" by returning Event(output=...) — typically gated by a counter or
state-key presence check.

See ADK _base_node.py:65-74 for the wait_for_output contract.
"""

from google.adk.workflow import FunctionNode


class JoinFunctionNode(FunctionNode):
    """FunctionNode with wait_for_output=True. Use for nodes with multiple
    unconditional incoming edges in the workflow graph."""
    wait_for_output: bool = True
