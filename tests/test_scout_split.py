"""Unit tests for nodes/scout_split.py — JSON parser + Candidate validator
+ cap-25 priority truncation. Per DESIGN.v2.md §6.1.

scout_split returns a STRING (the candidates serialized as JSON, with a
short prefix) so Triage's LlmAgent receives them in its user message.
The state["candidates"] field carries the typed Candidate list for
downstream nodes.
"""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

from nodes.scout_split import scout_split


def _ctx(state: dict) -> MagicMock:
    ctx = MagicMock()
    ctx.state = state
    return ctx


def _candidate_dict(title: str, source: str = "arxiv", url: str = None) -> dict:
    return {
        "title":        title,
        "url":          url or f"https://example.com/{title.replace(' ', '-')}",
        "source":       source,
        "published_at": datetime.now(timezone.utc).isoformat(),
        "raw_summary":  f"Summary for {title}",
    }


# --- Happy path -----------------------------------------------------------


def test_parses_clean_json_array():
    items = [_candidate_dict("Foo"), _candidate_dict("Bar")]
    ctx = _ctx({"scout_raw": json.dumps(items)})
    event = scout_split(None, ctx)
    assert isinstance(event.output, str)
    assert "Foo" in event.output
    assert "Bar" in event.output
    assert len(ctx.state["candidates"]) == 2
    assert ctx.state["candidates"][0].title in ("Foo", "Bar")


def test_strips_markdown_fences():
    items = [_candidate_dict("Foo")]
    ctx = _ctx({"scout_raw": f"```json\n{json.dumps(items)}\n```"})
    scout_split(None, ctx)
    assert len(ctx.state["candidates"]) == 1


def test_recovers_array_when_wrapped_in_prose():
    items = [_candidate_dict("Foo")]
    ctx = _ctx({"scout_raw": f"Here is the list:\n{json.dumps(items)}\nThanks."})
    scout_split(None, ctx)
    assert len(ctx.state["candidates"]) == 1


def test_handles_dict_wrapped_array():
    """Some LLMs emit `{"candidates": [...]}` even when prompted for a bare list."""
    items = [_candidate_dict("Foo")]
    ctx = _ctx({"scout_raw": json.dumps({"candidates": items})})
    scout_split(None, ctx)
    assert len(ctx.state["candidates"]) == 1


# --- Defensive parsing -----------------------------------------------------


def test_empty_raw_writes_empty_candidates():
    ctx = _ctx({"scout_raw": ""})
    scout_split(None, ctx)
    assert ctx.state["candidates"] == []


def test_invalid_json_writes_empty_candidates():
    ctx = _ctx({"scout_raw": "{not valid json"})
    scout_split(None, ctx)
    assert ctx.state["candidates"] == []


def test_drops_invalid_candidates_keeps_valid_ones():
    items = [
        _candidate_dict("Good"),
        {"title": "Bad — missing url", "source": "arxiv"},  # invalid
    ]
    ctx = _ctx({"scout_raw": json.dumps(items)})
    scout_split(None, ctx)
    assert len(ctx.state["candidates"]) == 1
    assert ctx.state["candidates"][0].title == "Good"


def test_dedupes_by_url():
    items = [
        _candidate_dict("First", url="https://x.com/dup"),
        _candidate_dict("Second", url="https://x.com/dup"),  # same URL
        _candidate_dict("Third", url="https://x.com/three"),
    ]
    ctx = _ctx({"scout_raw": json.dumps(items)})
    scout_split(None, ctx)
    assert len(ctx.state["candidates"]) == 2  # one of the dups dropped


# --- Cap-25 priority truncation -------------------------------------------


def test_caps_at_25_when_more_present():
    """30 candidates from same source — assert truncated to 25."""
    items = [_candidate_dict(f"P{i}", source="huggingface", url=f"https://x/{i}") for i in range(30)]
    ctx = _ctx({"scout_raw": json.dumps(items)})
    scout_split(None, ctx)
    assert len(ctx.state["candidates"]) == 25


def test_priority_keeps_named_labs_when_capping():
    """27 entries: 10 anthropic + 5 hackernews + 12 arxiv. Assert all named-lab
    posts (anthropic) survive when capping to 25, and hackernews loses some
    (lower priority)."""
    items = (
        [_candidate_dict(f"A{i}", source="anthropic", url=f"https://a/{i}") for i in range(10)]
        + [_candidate_dict(f"H{i}", source="hackernews", url=f"https://h/{i}") for i in range(5)]
        + [_candidate_dict(f"X{i}", source="arxiv", url=f"https://x/{i}") for i in range(12)]
    )
    assert len(items) == 27
    ctx = _ctx({"scout_raw": json.dumps(items)})
    scout_split(None, ctx)
    assert len(ctx.state["candidates"]) == 25
    sources = [c.source for c in ctx.state["candidates"]]
    assert sources.count("anthropic") == 10
    assert sources.count("arxiv") == 12
    assert sources.count("hackernews") == 3  # 25 - 10 - 12 = 3
