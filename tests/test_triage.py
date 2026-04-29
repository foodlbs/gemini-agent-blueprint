"""Tests for Triage agent and the Memory Bank wrapper.

Coverage maps to DESIGN.md §2 "Triage" scenarios:
- High-score candidate is novel → memory_bank_search returns empty (pass-through).
- Candidate matches a 'covered' fact → search returns hit (drop as duplicate).
- Candidate matches a 'human-rejected' fact → search returns hit (hard reject).
- No candidates → instruction encodes chosen_release=None + skip_reason.
"""

from datetime import datetime, timezone

import pytest

from shared.memory import (
    DEFAULT_SCOPE,
    MemoryBankClient,
    memory_bank_add_fact,
    memory_bank_search,
    reset_default_client,
)
from shared.models import Candidate, ChosenRelease


@pytest.fixture(autouse=True)
def isolated_memory_bank():
    """Each test runs with a fresh in-memory Memory Bank."""
    client = MemoryBankClient.in_memory()
    reset_default_client(client)
    yield client
    reset_default_client(None)


# --- Memory Bank: building-block behavior -----------------------------------


def test_add_fact_then_search_finds_it():
    memory_bank_add_fact(
        scope=DEFAULT_SCOPE,
        fact="Covered Anthropic Skills on 2026-04-22",
        metadata={"type": "covered", "release_url": "https://anthropic.com/skills"},
    )
    results = memory_bank_search("Have we encountered Anthropic Skills?")
    assert len(results) == 1
    assert results[0]["metadata"]["type"] == "covered"
    assert results[0]["score"] > 0.85


def test_search_returns_empty_when_memory_bank_is_empty():
    results = memory_bank_search("Have we encountered Anthropic Skills?")
    assert results == []


def test_search_returns_empty_for_unrelated_query():
    memory_bank_add_fact(
        scope=DEFAULT_SCOPE,
        fact="Covered Anthropic Skills on 2026-04-22",
        metadata={"type": "covered"},
    )
    results = memory_bank_search("Have we encountered OpenAI Whisper Three?")
    assert results == []


def test_search_preserves_full_metadata():
    metadata = {
        "type": "covered",
        "release_url": "https://anthropic.com/skills",
        "release_source": "anthropic",
        "release_published_at": "2026-04-22T10:00:00Z",
        "article_url": "https://medium.com/x",
        "covered_at": "2026-04-22T18:30:00Z",
    }
    memory_bank_add_fact(
        scope=DEFAULT_SCOPE,
        fact="Covered Anthropic Skills on 2026-04-22",
        metadata=metadata,
    )
    results = memory_bank_search("Have we encountered Anthropic Skills?")
    assert results[0]["metadata"] == metadata


# --- Triage scenario coverage -----------------------------------------------


def test_triage_high_score_candidate_passes_through_when_novel():
    """High-significance candidate, no Memory Bank match → search returns
    empty, novelty step clears (DESIGN.md §2 step 2 "novelty clear")."""
    candidate = Candidate(
        title="Anthropic Brand New Release",
        url="https://anthropic.com/new",
        source="anthropic",
        published_at=datetime.now(timezone.utc),
        raw_summary="A new artifact with working code and documentation.",
    )
    results = memory_bank_search(f"Have we encountered {candidate.title}?")
    assert results == []  # novel — Triage would let it through


def test_triage_dedupes_candidate_against_covered_fact():
    """Candidate matches a 'covered' fact → search returns the hit, Triage
    drops as duplicate (DESIGN.md §2 "If similarity > 0.85, drop as duplicate")."""
    memory_bank_add_fact(
        scope=DEFAULT_SCOPE,
        fact="Covered Anthropic Skills on 2026-04-22",
        metadata={
            "type": "covered",
            "release_url": "https://anthropic.com/skills",
            "release_source": "anthropic",
            "covered_at": "2026-04-22T18:30:00Z",
        },
    )
    candidate = Candidate(
        title="Anthropic Skills",
        url="https://anthropic.com/skills",
        source="anthropic",
        published_at=datetime.now(timezone.utc),
        raw_summary="A new artifact.",
    )
    results = memory_bank_search(f"Have we encountered {candidate.title}?")
    assert len(results) == 1
    assert results[0]["metadata"]["type"] == "covered"
    assert results[0]["score"] > 0.85


def test_triage_dedupes_candidate_against_human_rejected_fact():
    """Candidate matches a 'human-rejected' fact → hard reject (DESIGN.md
    §2 "Pay special attention to facts tagged human-rejected — those are
    hard rejects")."""
    memory_bank_add_fact(
        scope=DEFAULT_SCOPE,
        fact="Human rejected topic: Anthropic Computer Use",
        metadata={
            "type": "human-rejected",
            "release_url": "https://anthropic.com/cu",
            "release_source": "anthropic",
            "rejected_at": "2026-04-22T18:30:00Z",
        },
    )
    candidate = Candidate(
        title="Anthropic Computer Use",
        url="https://anthropic.com/cu",
        source="anthropic",
        published_at=datetime.now(timezone.utc),
        raw_summary="Computer use for agents.",
    )
    results = memory_bank_search(f"Have we encountered {candidate.title}?")
    assert len(results) == 1
    assert results[0]["metadata"]["type"] == "human-rejected"
    assert results[0]["score"] > 0.85


def test_triage_filters_both_fact_types_with_one_search():
    """Both covered and human-rejected facts coexist in scope; a query
    that matches one returns only that one."""
    memory_bank_add_fact(
        scope=DEFAULT_SCOPE,
        fact="Covered Anthropic Skills on 2026-04-22",
        metadata={"type": "covered"},
    )
    memory_bank_add_fact(
        scope=DEFAULT_SCOPE,
        fact="Human rejected topic: Anthropic Computer Use",
        metadata={"type": "human-rejected"},
    )
    results = memory_bank_search("Have we encountered Anthropic Skills?")
    assert len(results) == 1
    assert results[0]["metadata"]["type"] == "covered"

    results = memory_bank_search("Have we encountered Anthropic Computer Use?")
    assert len(results) == 1
    assert results[0]["metadata"]["type"] == "human-rejected"


def test_triage_no_candidates_branch_encoded_in_instruction():
    """Per DESIGN.md §2: 'If none clear, write state["chosen_release"] = None
    and state["skip_reason"]'. Verify the instruction commits to this so
    the agent's behavior on empty candidates is well-defined."""
    from shared.prompts import TRIAGE_INSTRUCTION

    assert "If none clear" in TRIAGE_INSTRUCTION
    assert "chosen_release" in TRIAGE_INSTRUCTION
    assert "null" in TRIAGE_INSTRUCTION  # JSON literal null for the None branch
    assert "skip_reason" in TRIAGE_INSTRUCTION


# --- Triage agent wiring ----------------------------------------------------


def test_triage_agent_configuration():
    from agents.triage.agent import triage

    assert triage.name == "triage"
    assert triage.model == "gemini-3.1-flash-lite-preview"
    tool_names = {getattr(t, "__name__", str(t)) for t in triage.tools}
    assert "memory_bank_search" in tool_names
    assert "write_state_json" in tool_names


def test_triage_instruction_loaded_verbatim_from_prompts():
    from agents.triage.agent import triage
    from shared.prompts import TRIAGE_INSTRUCTION

    assert triage.instruction == TRIAGE_INSTRUCTION
    assert "Triage" in triage.instruction
    assert "memory_bank_search" in triage.instruction
    assert "human-rejected" in triage.instruction


# --- ChosenRelease model: top_alternatives field is present -----------------


def test_chosen_release_carries_top_alternatives():
    """Triage's output contract requires a top_alternatives list capped at 2."""
    alt_a = Candidate(
        title="Alt A", url="https://a", source="anthropic",
        published_at=datetime.now(timezone.utc), raw_summary="x",
    )
    alt_b = Candidate(
        title="Alt B", url="https://b", source="openai",
        published_at=datetime.now(timezone.utc), raw_summary="y",
    )
    chosen = ChosenRelease(
        title="Winner",
        url="https://w",
        source="anthropic",
        published_at=datetime.now(timezone.utc),
        raw_summary="z",
        score=85,
        rationale="strong release with shipped code",
        top_alternatives=[alt_a, alt_b],
    )
    assert chosen.top_alternatives == [alt_a, alt_b]
    assert chosen.score == 85


def test_chosen_release_top_alternatives_capped_at_two():
    alt = Candidate(
        title="Alt", url="https://a", source="openai",
        published_at=datetime.now(timezone.utc), raw_summary="x",
    )
    with pytest.raises(Exception):
        ChosenRelease(
            title="Winner",
            url="https://w",
            source="anthropic",
            published_at=datetime.now(timezone.utc),
            raw_summary="z",
            score=85,
            rationale="strong release",
            top_alternatives=[alt, alt, alt],
        )


def test_chosen_release_defaults_to_empty_alternatives():
    chosen = ChosenRelease(
        title="Winner",
        url="https://w",
        source="anthropic",
        published_at=datetime.now(timezone.utc),
        raw_summary="z",
        score=75,
        rationale="ok release",
    )
    assert chosen.top_alternatives == []
