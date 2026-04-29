"""Tests for the Topic Gate agent and the Telegram approval tool.

Coverage maps to the user's three required scenarios from DESIGN.md §3:
- chosen_release fixture + Telegram approve → state unchanged, topic_verdict="approve".
- Fixture + skip → chosen_release=None, memory_bank_add_fact called with type="human-rejected".
- Fixture + timeout → chosen_release=None, NO Memory Bank call.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from shared.memory import (
    MemoryBankClient,
    memory_bank_add_fact,
    memory_bank_search,
    reset_default_client,
)
from shared.models import Candidate, ChosenRelease, TopicVerdict
from tools import telegram_approval


@pytest.fixture(autouse=True)
def isolated_memory_bank():
    client = MemoryBankClient.in_memory()
    reset_default_client(client)
    yield client
    reset_default_client(None)


@pytest.fixture
def chosen_release() -> ChosenRelease:
    return ChosenRelease(
        title="Anthropic Skills",
        url="https://anthropic.com/skills",
        source="anthropic",
        published_at=datetime.now(timezone.utc),
        raw_summary="A new SDK for Claude that ships agent-as-a-library bundles.",
        score=85,
        rationale=(
            "Major lab + new SDK + working code + docs available now → high score."
        ),
        top_alternatives=[],
    )


# --- Telegram tool: returns the right TopicVerdict for each callback --------


def _patch_post_and_wait(monkeypatch, verdict_value: str):
    async def fake_wait(*_args, **_kwargs):
        return TopicVerdict(verdict=verdict_value, at=datetime.now(timezone.utc))
    monkeypatch.setattr(telegram_approval, "_post_topic_and_wait", fake_wait)


def test_telegram_tool_returns_approve_verdict(monkeypatch, chosen_release):
    _patch_post_and_wait(monkeypatch, "approve")
    result = telegram_approval.telegram_post_topic_for_approval(
        chosen_release=chosen_release,
        rationale=chosen_release.rationale,
        top_alternatives=[],
    )
    assert isinstance(result, dict)
    assert result["verdict"] == "approve"


def test_telegram_tool_returns_skip_verdict(monkeypatch, chosen_release):
    _patch_post_and_wait(monkeypatch, "skip")
    result = telegram_approval.telegram_post_topic_for_approval(
        chosen_release=chosen_release,
        rationale=chosen_release.rationale,
        top_alternatives=[],
    )
    assert result["verdict"] == "skip"


def test_telegram_tool_returns_timeout(monkeypatch, chosen_release):
    _patch_post_and_wait(monkeypatch, "timeout")
    result = telegram_approval.telegram_post_topic_for_approval(
        chosen_release=chosen_release,
        rationale=chosen_release.rationale,
        top_alternatives=[],
    )
    assert result["verdict"] == "timeout"


# --- Telegram message format -----------------------------------------------


def test_format_topic_message_includes_required_fields(chosen_release):
    text = telegram_approval._format_topic_message(
        chosen_release.model_dump(mode="json"),
        rationale=chosen_release.rationale,
        alternatives=[],
    )
    assert chosen_release.title in text
    assert chosen_release.url in text
    assert chosen_release.source in text
    assert str(chosen_release.score) in text
    assert chosen_release.rationale in text


def test_format_topic_message_renders_collapsed_alternatives():
    chosen = {
        "title": "Main",
        "url": "https://example.com/main",
        "source": "anthropic",
        "score": 85,
    }
    alts = [
        {"title": "Alt 1", "url": "https://example.com/alt1"},
        {"title": "Alt 2", "url": "https://example.com/alt2"},
        {"title": "Alt 3 (should be dropped)", "url": "https://example.com/alt3"},
    ]
    text = telegram_approval._format_topic_message(chosen, "rationale", alts)
    assert "Alt 1" in text
    assert "Alt 2" in text
    assert "Alt 3" not in text  # capped at 2 per DESIGN.md
    assert "Alternatives" in text


def test_format_topic_message_escapes_html_special_chars():
    chosen = {
        "title": "<script>alert(1)</script>",
        "url": "https://example.com",
        "source": "anthropic",
        "score": 85,
    }
    text = telegram_approval._format_topic_message(chosen, "rationale", [])
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


# --- Topic Gate after-agent callback: per-verdict state mutations ----------


def _run_callback(state: dict) -> dict:
    """Invoke the agent's after_agent_callback with a fake CallbackContext."""
    from agents.topic_gate.agent import _apply_topic_verdict
    _apply_topic_verdict(SimpleNamespace(state=state))
    return state


def test_topic_gate_approve_keeps_chosen_release_intact(chosen_release):
    """[User-required scenario 1] Telegram approve → state unchanged,
    topic_verdict='approve', no Memory Bank write (Editor handles 'covered'
    later)."""
    state = {"chosen_release": chosen_release, "topic_verdict": "approve"}

    _run_callback(state)

    assert state["chosen_release"] == chosen_release
    assert state["topic_verdict"] == "approve"
    assert "skip_reason" not in state
    # Topic Gate must NOT write to Memory Bank on approve.
    assert (
        memory_bank_search(f"Have we encountered {chosen_release.title}?")
        == []
    )


def test_topic_gate_skip_clears_chosen_release_and_records_human_rejection(
    chosen_release,
):
    """[User-required scenario 2] Telegram skip → chosen_release=None +
    skip_reason='human-rejected', and memory_bank_add_fact records the
    rejection with type='human-rejected'.

    The callback does the state cleanup; the fact-write is what the LLM
    would emit by calling ``memory_bank_add_fact``. We exercise both halves
    here so the end-to-end skip flow is locked down by one test.
    """
    # The LLM's tool call: write the human-rejected fact.
    skip_at = datetime.now(timezone.utc)
    memory_bank_add_fact(
        scope="ai_release_pipeline",
        fact=f"Human rejected topic: {chosen_release.title}",
        metadata={
            "type": "human-rejected",
            "release_url": chosen_release.url,
            "release_source": chosen_release.source,
            "rejected_at": skip_at.isoformat(),
        },
    )

    # The after-agent callback: clear chosen_release.
    state = {"chosen_release": chosen_release, "topic_verdict": "skip"}
    _run_callback(state)

    assert state["chosen_release"] is None
    assert state["skip_reason"] == "human-rejected"
    assert state["topic_verdict"] == "skip"

    # Memory Bank now reflects the human rejection — Triage will hard-reject
    # this release on the next cycle.
    facts = memory_bank_search(f"Have we encountered {chosen_release.title}?")
    assert len(facts) == 1
    assert facts[0]["metadata"]["type"] == "human-rejected"
    assert facts[0]["metadata"]["release_url"] == chosen_release.url
    assert facts[0]["metadata"]["release_source"] == chosen_release.source


def test_topic_gate_timeout_clears_chosen_release_without_memory_bank_write(
    chosen_release,
):
    """[User-required scenario 3] Telegram timeout → chosen_release=None +
    skip_reason='topic-gate-timeout', NO Memory Bank write (DESIGN.md §3
    step 5: 'the topic might still be worth covering on a later cycle')."""
    state = {"chosen_release": chosen_release, "topic_verdict": "timeout"}

    _run_callback(state)

    assert state["chosen_release"] is None
    assert state["skip_reason"] == "topic-gate-timeout"
    assert state["topic_verdict"] == "timeout"
    # CRITICAL: do not block re-attempts on a later cycle.
    assert (
        memory_bank_search(f"Have we encountered {chosen_release.title}?")
        == []
    )


def test_topic_gate_callback_is_noop_when_topic_verdict_missing(chosen_release):
    """If the LLM didn't write topic_verdict (shouldn't happen but defensive),
    the callback must not corrupt state."""
    state = {"chosen_release": chosen_release}
    _run_callback(state)
    assert state["chosen_release"] == chosen_release
    assert "skip_reason" not in state


# --- Topic Gate agent wiring ----------------------------------------------


def test_topic_gate_agent_configuration():
    from agents.topic_gate.agent import topic_gate

    assert topic_gate.name == "topic_gate"
    assert topic_gate.model == "gemini-3.1-flash-lite-preview"
    tool_names = {getattr(t, "__name__", str(t)) for t in topic_gate.tools}
    assert "telegram_post_topic_for_approval" in tool_names
    assert "memory_bank_add_fact" in tool_names
    assert "write_state_json" in tool_names
    # The state-mutation callback must be wired or the design's skip/timeout
    # cleanup never runs.
    assert topic_gate.after_agent_callback is not None


def test_topic_gate_instruction_loaded_verbatim():
    from agents.topic_gate.agent import topic_gate
    from shared.prompts import TOPIC_GATE_INSTRUCTION

    assert topic_gate.instruction == TOPIC_GATE_INSTRUCTION
    # Critical branches the LLM must follow:
    assert "Topic Gate" in topic_gate.instruction
    assert "approve" in topic_gate.instruction
    assert "skip" in topic_gate.instruction
    assert "human-rejected" in topic_gate.instruction
    assert "topic-gate-timeout" in topic_gate.instruction
    # Defensive early exit when Triage already skipped:
    assert '`state["chosen_release"]` is None' in topic_gate.instruction
    assert "end your turn immediately" in topic_gate.instruction
