"""Unit tests for nodes/aggregation.gather_research — counter-gated join.

See docs/superpowers/specs/2026-05-01-fan-in-join-design.md."""

from types import SimpleNamespace

from nodes.aggregation import _gather_research_impl


def _stub_ctx(state=None):
    """Minimal Context stub — _gather_research_impl only reads ctx.state."""
    return SimpleNamespace(state=state if state is not None else {})


# Realistic researcher payloads (raw JSON strings, as ADK output_key writes them).
_DOCS_RAW = '{"summary": "docs summary"}'
_GH_RAW = (
    '{"summary": "github summary",'
    ' "repo_meta": {"stars": 10, "forks": 1},'
    ' "readme_excerpt": "RE",'
    ' "file_list": ["README.md"]}'
)
_CONTEXT_RAW = (
    '{"summary": "context summary",'
    ' "reactions": ["+1"],'
    ' "related_releases": ["r-1"]}'
)


def _seed_state():
    return {
        "docs_research":    _DOCS_RAW,
        "github_research":  _GH_RAW,
        "context_research": _CONTEXT_RAW,
    }


def test_gather_research_returns_no_output_on_first_call():
    """First trigger increments counter to 1; node must stay WAITING
    (Event with no output) so ADK re-triggers it on the next predecessor."""
    ctx = _stub_ctx(state=_seed_state())
    result = _gather_research_impl(node_input=None, ctx=ctx)
    assert result.output is None
    assert ctx.state["gather_research_call_count"] == 1
    assert "research" not in ctx.state


def test_gather_research_returns_no_output_on_second_call():
    """Second trigger increments counter to 2; still WAITING."""
    ctx = _stub_ctx(state={**_seed_state(), "gather_research_call_count": 1})
    result = _gather_research_impl(node_input=None, ctx=ctx)
    assert result.output is None
    assert ctx.state["gather_research_call_count"] == 2
    assert "research" not in ctx.state


def test_gather_research_yields_merged_dossier_on_third_call():
    """Third trigger advances counter to 3 → join proceeds: output present
    AND state['research'] is the merged ResearchDossier."""
    ctx = _stub_ctx(state={**_seed_state(), "gather_research_call_count": 2})
    result = _gather_research_impl(node_input=None, ctx=ctx)
    assert ctx.state["gather_research_call_count"] == 3
    # Output is non-None (the sections_filled dict).
    assert result.output is not None
    assert "sections_filled" in result.output
    # Merged dossier landed in state.
    merged = ctx.state["research"]
    assert merged is not None
    assert merged.summary == "docs summary"  # docs wins precedence
    assert merged.repo_meta == {"stars": 10, "forks": 1}
    assert merged.reactions == ["+1"]
