"""Tests for the Editor agent: medium_format, telegram_post_for_approval,
and the editor LlmAgent's three-way verdict branching.

Coverage maps to the user's three required scenarios from DESIGN.md §9:
- draft + image_assets + video_asset + repo_url + Approve verdict →
  final_article populated, escalates, memory_bank_add_fact recorded once.
- Revise verdict → editor_verdict="revise", human_feedback set, no escalate,
  memory_bank_add_fact NOT called.
- Reject verdict → editor_verdict="reject", escalates, no Memory Bank call.
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from google.adk.events import EventActions

from shared.memory import (
    MemoryBankClient,
    memory_bank_add_fact,
    memory_bank_search,
    reset_default_client,
)
from shared.models import EditorVerdict
from tools import medium, telegram_approval


def _tool_name(t) -> str:
    return getattr(t, "__name__", None) or getattr(t, "name", "") or t.__class__.__name__


# --- tools/medium.py ------------------------------------------------------


def test_medium_format_returns_empty_for_empty_input():
    assert medium.medium_format("") == ""
    assert medium.medium_format(None) == ""


def test_medium_format_keeps_first_h1_and_demotes_subsequent_to_h2():
    md = "# Title\n\nbody\n\n# Stray heading\n\nmore body"
    out = medium.medium_format(md)
    assert "# Title" in out
    assert "## Stray heading" in out
    # No second '# Stray' line
    assert out.count("\n# ") == 0  # only the leading H1


def test_medium_format_adds_python_to_unmarked_code_fences():
    md = "intro\n\n```\nprint('hi')\n```\n\nouttro"
    out = medium.medium_format(md)
    assert "```python" in out
    # The opener should not remain as bare ```
    assert "```\nprint" not in out


def test_medium_format_preserves_existing_language_label():
    md = "intro\n\n```js\nconsole.log('x')\n```"
    out = medium.medium_format(md)
    assert "```js" in out
    assert "```python" not in out


def test_medium_format_collapses_excessive_blank_lines():
    md = "para 1\n\n\n\n\npara 2"
    out = medium.medium_format(md)
    assert "\n\n\n" not in out
    # Single blank line between paragraphs is preserved
    assert "para 1\n\npara 2" in out


def test_medium_format_preserves_image_and_link_markdown():
    md = (
        "# Title\n\n"
        "![cover](https://example.com/cover.png)\n\n"
        "Body. [download MP4](https://example.com/tutorial.mp4)\n"
    )
    out = medium.medium_format(md)
    assert "![cover](https://example.com/cover.png)" in out
    assert "[download MP4](https://example.com/tutorial.mp4)" in out


# --- tools/telegram_approval.telegram_post_for_approval -------------------


def _patch_editor_wait(monkeypatch, verdict_value: str, feedback: str | None = None):
    async def fake(*_args, **_kwargs):
        return EditorVerdict(
            verdict=verdict_value,
            feedback=feedback,
            at=datetime.now(timezone.utc),
        )
    monkeypatch.setattr(telegram_approval, "_post_editor_and_wait", fake)


def test_telegram_post_for_approval_returns_approve_verdict(monkeypatch):
    _patch_editor_wait(monkeypatch, "approve")
    result = telegram_approval.telegram_post_for_approval(
        article="An article body.",
        repo_url="https://github.com/x/y",
        asset_summary="1 cover + 2 inline, 8s GIF, repo ✓",
    )
    assert result["verdict"] == "approve"
    assert result["feedback"] is None


def test_telegram_post_for_approval_returns_revise_with_feedback(monkeypatch):
    _patch_editor_wait(monkeypatch, "revise", feedback="tighten section 2")
    result = telegram_approval.telegram_post_for_approval(
        article="An article body.",
        repo_url=None,
        asset_summary="1 cover only",
    )
    assert result["verdict"] == "revise"
    assert result["feedback"] == "tighten section 2"


def test_telegram_post_for_approval_returns_reject(monkeypatch):
    _patch_editor_wait(monkeypatch, "reject")
    result = telegram_approval.telegram_post_for_approval(
        "article", "https://r", "summary"
    )
    assert result["verdict"] == "reject"
    assert result["feedback"] is None


def test_telegram_post_for_approval_returns_pending_human_on_timeout(monkeypatch):
    _patch_editor_wait(monkeypatch, "pending_human")
    result = telegram_approval.telegram_post_for_approval(
        "article", None, "summary"
    )
    assert result["verdict"] == "pending_human"


def test_format_editor_message_includes_required_fields():
    text = telegram_approval._format_editor_message(
        article="An article body that's reasonably short.",
        repo_url="https://github.com/x/y",
        asset_summary="1 cover + 2 inline images, 8s tutorial GIF, GitHub repo ✓",
    )
    assert "Editor" in text
    assert "github.com/x/y" in text
    assert "1 cover + 2 inline" in text
    assert "An article body" in text


def test_format_editor_message_truncates_long_article():
    long_article = "x" * (telegram_approval.EDITOR_PREVIEW_LIMIT + 200)
    text = telegram_approval._format_editor_message(
        article=long_article,
        repo_url="",
        asset_summary="cover only",
    )
    # Truncation marker present and within limit
    assert "…" in text


def test_format_editor_message_omits_repo_when_none():
    text = telegram_approval._format_editor_message(
        article="body", repo_url="", asset_summary="cover only",
    )
    assert "Repo:" not in text


def test_format_editor_message_escapes_html():
    text = telegram_approval._format_editor_message(
        article="<script>x</script>", repo_url="", asset_summary="<bad>",
    )
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


# --- Editor agent wiring --------------------------------------------------


def test_editor_agent_wiring():
    from agents.editor.agent import editor
    assert editor.name == "editor"
    assert editor.model == "gemini-3.1-pro-preview"
    names = {_tool_name(t) for t in editor.tools}
    assert names == {
        "medium_format", "telegram_post_for_approval", "memory_bank_add_fact"
    }
    assert editor.output_key == "editor_output_blob"
    assert editor.before_agent_callback is not None
    assert editor.after_agent_callback is not None
    assert editor.after_tool_callback is not None


def test_editor_instruction_first_line_is_chosen_release_early_exit():
    from agents.editor.agent import editor
    first = editor.instruction.splitlines()[0]
    assert first == "If state['chosen_release'] is None, end your turn immediately without using tools."


def test_editor_instruction_encodes_three_way_branching_and_constraints():
    from agents.editor.agent import editor
    instr = editor.instruction
    # Three+ verdicts must all be named
    for verdict in ("approve", "reject", "revise", "pending_human"):
        assert verdict in instr
    # Memory Bank only on approve, only once per loop
    assert "memory_bank_add_fact" in instr
    assert "memory_bank_recorded" in instr
    # Asset re-weaving rules
    assert "image_assets" in instr
    assert "<!-- IMAGE: <position> -->" in instr
    assert "<!-- VIDEO: hero -->" in instr
    assert "video_asset" in instr
    # Repo link integration
    assert "repo_url" in instr
    # Format-then-post sequence
    assert "medium_format" in instr
    assert "telegram_post_for_approval" in instr


# --- Editor scenarios (the three user-required ones) ----------------------


@pytest.fixture(autouse=True)
def isolated_memory_bank():
    """Each test runs with a fresh in-memory MemoryBank."""
    client = MemoryBankClient.in_memory()
    reset_default_client(client)
    yield client
    reset_default_client(None)


@pytest.fixture
def editor_input_state() -> dict:
    """Fixture: draft with all markers + image_assets + video_asset + repo_url."""
    return {
        "chosen_release": SimpleNamespace(
            title="Anthropic Skills",
            url="https://anthropic.com/skills",
            source="anthropic",
        ),
        "draft": (
            "# Build with Anthropic Skills\n## Agents as importable libraries\n\n"
            "<!-- IMAGE: cover -->\n\n"
            "## Setup\nInstall the SDK.\n\n"
            "<!-- IMAGE: after-section-1 -->\n\n"
            "## First skill\n```python\nprint('hi')\n```\n\n"
            "<!-- VIDEO: hero -->\n"
        ),
        "image_assets": [
            {"position": "cover", "url": "https://gcs/cover.png",
             "alt_text": "stylized stack of skill bundles", "aspect_ratio": "16:9"},
            {"position": "after-section-1", "url": "https://gcs/inline-1.png",
             "alt_text": "install flow diagram", "aspect_ratio": "16:9"},
        ],
        "video_asset": {
            "mp4_url": "https://gcs/tutorial.mp4",
            "gif_url": "https://gcs/tutorial.gif",
            "poster_url": "https://gcs/tutorial-poster.jpg",
            "duration_seconds": 6,
        },
        "repo_url": "https://github.com/x/anthropic-skills-quickstart",
    }


def _run_after_callback(state: dict, actions: EventActions | None = None) -> EventActions:
    from agents.editor.agent import _split_editor_output
    actions = actions or EventActions()
    _split_editor_output(SimpleNamespace(state=state, actions=actions))
    return actions


def test_editor_approve_populates_final_article_and_escalates(editor_input_state):
    """[Scenario 1] Approve → final_article populated, escalates to break loop."""
    state = {
        **editor_input_state,
        "editor_output_blob": json.dumps({
            "editor_verdict": "approve",
            "final_article": (
                "# Build with Anthropic Skills\n"
                "![stylized stack](https://gcs/cover.png)\n"
                "...polished article body with all assets woven in..."
            ),
            "medium_draft_url": "https://medium.com/p/draft-abc",
            "human_feedback": None,
        }),
    }
    actions = _run_after_callback(state)

    assert state["editor_verdict"] == "approve"
    assert "Build with Anthropic Skills" in state["final_article"]
    assert "https://gcs/cover.png" in state["final_article"]
    assert state["medium_draft_url"] == "https://medium.com/p/draft-abc"
    # Approve must escalate so the LoopAgent exits.
    assert actions.escalate is True


def test_editor_approve_records_covered_fact_via_memory_bank(editor_input_state):
    """[Scenario 1, the "memory_bank_add_fact called once" half]
    When the LLM calls memory_bank_add_fact on approve, the 'covered' fact
    is recorded in Memory Bank with the right metadata. We verify by
    invoking the tool directly with the metadata the instruction prescribes
    and asserting it's searchable.
    """
    chosen = editor_input_state["chosen_release"]
    memory_bank_add_fact(
        scope="ai_release_pipeline",
        fact=f"Covered {chosen.title} on 2026-04-22",
        metadata={
            "type": "covered",
            "release_url": chosen.url,
            "release_source": chosen.source,
            "release_published_at": "2026-04-22T10:00:00Z",
            "article_url": "https://medium.com/p/draft-abc",
            "repo_url": editor_input_state["repo_url"],
            "asset_bundle": {
                "cover_url": "https://gcs/cover.png",
                "video_url": "https://gcs/tutorial.mp4",
            },
            "covered_at": "2026-04-22T18:30:00Z",
        },
    )
    facts = memory_bank_search(f"Have we encountered {chosen.title}?")
    assert len(facts) == 1
    assert facts[0]["metadata"]["type"] == "covered"
    assert facts[0]["metadata"]["release_url"] == chosen.url
    assert facts[0]["metadata"]["repo_url"] == editor_input_state["repo_url"]


def test_editor_revise_records_feedback_without_escalating(editor_input_state):
    """[Scenario 2] Revise → editor_verdict='revise', human_feedback set,
    no escalate (loop continues to Revision Writer), no Memory Bank write."""
    state = {
        **editor_input_state,
        "editor_output_blob": json.dumps({
            "editor_verdict": "revise",
            "final_article": None,
            "medium_draft_url": None,
            "human_feedback": "tighten section 2 and add a working example",
        }),
    }
    actions = _run_after_callback(state)

    assert state["editor_verdict"] == "revise"
    assert state["human_feedback"] == "tighten section 2 and add a working example"
    # Revise must NOT escalate — the loop runs Revision Writer next.
    assert actions.escalate is not True
    # No Memory Bank write should have been recorded by side effect.
    chosen = editor_input_state["chosen_release"]
    assert memory_bank_search(f"Have we encountered {chosen.title}?") == []


def test_editor_reject_writes_verdict_and_escalates_without_memory_bank(
    editor_input_state,
):
    """[Scenario 3] Reject → editor_verdict='reject', escalates, NO Memory
    Bank write (a rejected article shouldn't block re-attempts later)."""
    state = {
        **editor_input_state,
        "editor_output_blob": json.dumps({
            "editor_verdict": "reject",
            "final_article": "(latest polished version, archived for reference)",
            "medium_draft_url": None,
            "human_feedback": None,
        }),
    }
    actions = _run_after_callback(state)

    assert state["editor_verdict"] == "reject"
    assert state["final_article"]
    assert actions.escalate is True
    # CRITICAL: no Memory Bank write on reject.
    chosen = editor_input_state["chosen_release"]
    assert memory_bank_search(f"Have we encountered {chosen.title}?") == []
    # The "memory_bank_recorded" flag must not be flipped (only the
    # after_tool_callback would set it, and that only fires on the
    # memory_bank_add_fact tool call).
    assert "memory_bank_recorded" not in state


def test_editor_pending_human_escalates_with_no_memory_bank(editor_input_state):
    """Timeout → pending_human verdict, escalates, no Memory Bank write."""
    state = {
        **editor_input_state,
        "editor_output_blob": json.dumps({
            "editor_verdict": "pending_human",
            "final_article": "(article waiting on human)",
            "medium_draft_url": None,
            "human_feedback": None,
        }),
    }
    actions = _run_after_callback(state)
    assert state["editor_verdict"] == "pending_human"
    assert actions.escalate is True


# --- after_tool_callback flips memory_bank_recorded -----------------------


def test_after_tool_callback_flips_memory_bank_recorded_on_add_fact():
    """When the LLM calls memory_bank_add_fact, the after_tool callback
    sets state['memory_bank_recorded']=True so subsequent loop iterations
    skip the Memory Bank call (DESIGN.md §9 'never re-add')."""
    from agents.editor.agent import _track_memory_bank_writes
    state = {}
    ctx = SimpleNamespace(state=state)
    fake_tool = MagicMock()
    fake_tool.name = "memory_bank_add_fact"

    _track_memory_bank_writes(
        tool=fake_tool, args={}, tool_context=ctx, tool_response={"ok": True},
    )
    assert state["memory_bank_recorded"] is True


def test_after_tool_callback_ignores_other_tools():
    from agents.editor.agent import _track_memory_bank_writes
    state = {}
    ctx = SimpleNamespace(state=state)
    fake_tool = MagicMock()
    fake_tool.name = "telegram_post_for_approval"

    _track_memory_bank_writes(
        tool=fake_tool, args={}, tool_context=ctx, tool_response={"verdict": "approve"},
    )
    assert "memory_bank_recorded" not in state


# --- before_agent_callback: programmatic early exit -----------------------


def test_before_callback_returns_skip_when_chosen_release_is_none():
    from agents.editor.agent import _early_exit_if_no_chosen_release
    ctx = SimpleNamespace(state={"chosen_release": None})
    result = _early_exit_if_no_chosen_release(ctx)
    assert result is not None
    assert "skipped" in result.parts[0].text.lower()


def test_before_callback_lets_agent_run_when_chosen_release_set():
    from agents.editor.agent import _early_exit_if_no_chosen_release
    ctx = SimpleNamespace(state={"chosen_release": "x"})
    assert _early_exit_if_no_chosen_release(ctx) is None
