"""Unit tests for tools/memory.py (the v2 Memory Bank adapter).

Per DESIGN.v2.md §7.2 test list. These tests run against
InMemoryMemoryService (set MEMORY_BANK_BACKEND=inmemory). The live
Vertex round-trip lives in tests/smoke/memory_smoke.py.
"""

import os
from unittest.mock import patch

import pytest

# Force inmemory backend BEFORE importing tools.memory so the singleton
# initializes correctly the first time.
os.environ["MEMORY_BANK_BACKEND"] = "inmemory"

from tools import memory  # noqa: E402
from tools.memory import (  # noqa: E402
    DUPLICATE_SIMILARITY_THRESHOLD,
    _build_service,
    _decode_fact,
    _encode_fact_with_metadata,
    memory_bank_add_fact,
    memory_bank_search,
    reset_default_service,
)


@pytest.fixture(autouse=True)
def _isolate_singleton():
    """Each test starts with a fresh InMemoryMemoryService."""
    reset_default_service(None)
    yield
    reset_default_service(None)


# --- Public API contract ---------------------------------------------------


def test_memory_search_returns_dict_shape():
    """Each search hit MUST have keys 'fact', 'score', 'metadata'."""
    memory_bank_add_fact(
        scope="ai_release_pipeline",
        fact="Covered: ACME Foo",
        metadata={
            "type": "covered",
            "release_url": "https://example.com/foo",
            "release_source": "arxiv",
        },
    )
    results = memory_bank_search("ACME Foo")
    assert results, "expected at least one hit"
    for r in results:
        assert set(r.keys()) >= {"fact", "score", "metadata"}
        assert isinstance(r["fact"], str)
        assert isinstance(r["score"], float)
        assert isinstance(r["metadata"], dict)


def test_memory_add_fact_round_trip():
    """add_fact + search round-trip preserves the fact text and metadata."""
    memory_bank_add_fact(
        scope="ai_release_pipeline",
        fact="Human rejected topic: ACME Bar",
        metadata={
            "type": "human-rejected",
            "release_url": "https://example.com/bar",
            "release_source": "anthropic",
            "rejected_at": "2026-04-29T00:00:00Z",
        },
    )
    results = memory_bank_search("ACME Bar")
    assert len(results) >= 1
    hit = results[0]
    assert "Human rejected topic: ACME Bar" in hit["fact"]
    # Metadata round-trip is the contract — Triage's hard-reject depends on it.
    assert hit["metadata"]["type"] == "human-rejected"
    assert hit["metadata"]["release_url"] == "https://example.com/bar"


# --- Validation guards (caller-bug class) ----------------------------------


def test_memory_add_fact_metadata_type_required():
    with pytest.raises(ValueError, match="metadata\\['type'\\] is required"):
        memory_bank_add_fact(
            scope="ai_release_pipeline",
            fact="Bad fact",
            metadata={"release_url": "https://x", "release_source": "arxiv"},
        )


def test_memory_add_fact_metadata_type_must_be_known():
    with pytest.raises(ValueError, match="must be 'covered' or 'human-rejected'"):
        memory_bank_add_fact(
            scope="ai_release_pipeline",
            fact="Bad fact",
            metadata={
                "type": "topic-skipped",  # invalid per §9.1
                "release_url": "https://x",
                "release_source": "arxiv",
            },
        )


def test_memory_add_fact_release_url_required():
    with pytest.raises(ValueError, match="release_url"):
        memory_bank_add_fact(
            scope="ai_release_pipeline",
            fact="Bad fact",
            metadata={"type": "covered", "release_source": "arxiv"},
        )


def test_memory_add_fact_release_source_required():
    with pytest.raises(ValueError, match="release_source"):
        memory_bank_add_fact(
            scope="ai_release_pipeline",
            fact="Bad fact",
            metadata={"type": "covered", "release_url": "https://x"},
        )


# --- Fail-open contract (transport errors) ---------------------------------


def test_memory_search_returns_empty_on_service_error(caplog):
    """Per §12.3 — search must return [] on backend error, not raise."""
    class ExplodingService:
        async def search_memory(self, **kwargs):
            raise RuntimeError("memory bank exploded")
    reset_default_service(ExplodingService())  # type: ignore[arg-type]

    results = memory_bank_search("anything")

    assert results == []
    assert any("memory_bank_search failed" in rec.message for rec in caplog.records)


def test_memory_add_fact_returns_false_on_service_error(caplog):
    """Per §12.3 — add_fact must return False on backend error, not raise."""
    class ExplodingService:
        async def add_session_to_memory(self, session):
            raise RuntimeError("memory bank exploded")
    reset_default_service(ExplodingService())  # type: ignore[arg-type]

    ok = memory_bank_add_fact(
        scope="ai_release_pipeline",
        fact="Will fail",
        metadata={
            "type": "covered",
            "release_url": "https://example.com/fail",
            "release_source": "arxiv",
        },
    )

    assert ok is False
    assert any("memory_bank_add_fact failed" in rec.message for rec in caplog.records)


# --- Backend factory --------------------------------------------------------


def test_factory_picks_inmemory_when_env_set(monkeypatch):
    monkeypatch.setenv("MEMORY_BANK_BACKEND", "inmemory")
    service = _build_service()
    from google.adk.memory import InMemoryMemoryService
    assert isinstance(service, InMemoryMemoryService)


def test_factory_picks_vertex_when_env_set(monkeypatch):
    monkeypatch.setenv("MEMORY_BANK_BACKEND", "vertex")
    monkeypatch.setenv("MEMORY_BANK_ID", "projects/x/locations/us-west1/memoryBanks/y")
    # Construction may hit the network; mock the constructor.
    from google.adk.memory import VertexAiMemoryBankService
    with patch.object(VertexAiMemoryBankService, "__init__", return_value=None) as mocked:
        service = _build_service()
    assert isinstance(service, VertexAiMemoryBankService)
    assert mocked.called


def test_factory_raises_when_vertex_chosen_but_id_missing(monkeypatch):
    monkeypatch.setenv("MEMORY_BANK_BACKEND", "vertex")
    monkeypatch.delenv("MEMORY_BANK_ID", raising=False)
    with pytest.raises(RuntimeError, match="MEMORY_BANK_ID must be set"):
        _build_service()


def test_factory_rejects_unknown_backend(monkeypatch):
    monkeypatch.setenv("MEMORY_BANK_BACKEND", "redis-bunny-mode")
    with pytest.raises(ValueError, match="Unknown MEMORY_BANK_BACKEND"):
        _build_service()


# --- Encoding helpers (private; tested directly because Triage depends) ---


def test_encode_decode_round_trip():
    fact = "Covered: ACME Foo"
    metadata = {"type": "covered", "release_url": "https://x", "k": 1}
    encoded = _encode_fact_with_metadata(fact, metadata)
    clean, decoded = _decode_fact(encoded)
    assert clean == fact
    assert decoded == metadata


def test_decode_handles_text_without_metadata():
    clean, decoded = _decode_fact("Just a fact, no metadata.")
    assert clean == "Just a fact, no metadata."
    assert decoded == {}


def test_decode_tolerates_corrupt_metadata_json():
    clean, decoded = _decode_fact("Some fact\n<!-- airel_metadata: {not-json -->")
    assert clean == "Some fact"
    assert decoded == {}


# --- Cross-cutting: similarity threshold constant matches design -----------


def test_similarity_threshold_matches_design():
    # DESIGN.v2.md §9.3 specifies 0.85.
    assert DUPLICATE_SIMILARITY_THRESHOLD == 0.85
