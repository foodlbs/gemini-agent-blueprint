"""Memory Bank wrapper for the AI release pipeline.

Per DESIGN.md "Memory Bank schema", two fact types live here:

- ``covered`` — written by the Editor on Approve, recording a published release.
- ``human-rejected`` — written by the Topic Gate on Skip, blocking re-surfacing.

Triage searches against both with similarity threshold ``0.85``; both are
hard filters — the same release won't re-surface after either outcome.

Backend
-------
v1 ships an in-process ``LocalBackend`` with a stopword-filtered token-overlap
similarity stand-in. Production wiring to Vertex AI Memory Bank lives at the
deploy step (DESIGN.md "Deployment & triggering").
"""

import logging
import re
from datetime import datetime, timezone
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_SCOPE = "ai_release_pipeline"

_STOPWORDS = {
    "have", "has", "had", "the", "and", "for", "with", "from", "into",
    "this", "that", "these", "those", "are", "was", "were", "been", "being",
    # Template words that appear in every query/fact per DESIGN.md schema:
    "encountered", "encounter", "covered", "release", "rejected", "topic",
}

_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)


class LocalBackend:
    """In-process dict backend. Stand-in for Vertex Memory Bank in tests/dev."""

    def __init__(self):
        self._facts: list[dict] = []
        self._lock = Lock()

    def search(self, scope: str, query: str, threshold: float) -> list[dict]:
        results: list[dict] = []
        with self._lock:
            for fact in self._facts:
                if fact["scope"] != scope:
                    continue
                score = _similarity(query, fact["fact"])
                if score > threshold:
                    results.append({**fact, "score": score})
        return results

    def add_fact(self, scope: str, fact: str, metadata: dict) -> None:
        with self._lock:
            self._facts.append({
                "scope": scope,
                "fact": fact,
                "metadata": dict(metadata),
                "added_at": datetime.now(timezone.utc).isoformat(),
            })


class MemoryBankClient:
    """Pipeline-facing Memory Bank wrapper.

    Two methods, mirroring the design's tool functions:

    - ``search(query, threshold=0.85)`` — return facts above similarity threshold.
    - ``add_fact(scope, fact, metadata)`` — persist a typed fact.

    Construct directly to inject a backend (useful in tests). The module-level
    ``memory_bank_search`` and ``memory_bank_add_fact`` functions delegate to
    a singleton client built from the environment.
    """

    def __init__(
        self,
        *,
        scope: str = DEFAULT_SCOPE,
        backend: Optional[LocalBackend] = None,
    ):
        self.scope = scope
        self._backend = backend or LocalBackend()

    @classmethod
    def in_memory(cls, scope: str = DEFAULT_SCOPE) -> "MemoryBankClient":
        """Construct with a fresh local backend. Convenience for tests."""
        return cls(scope=scope, backend=LocalBackend())

    def search(self, query: str, threshold: float = 0.85) -> list[dict]:
        """Search Memory Bank for facts matching ``query``.

        Returns the subset of stored facts within ``self.scope`` whose
        similarity to ``query`` exceeds ``threshold``. Errors are logged
        and surface as an empty list — Triage's dedupe treats "no match"
        and "search failed" identically (both let the candidate through).

        Args:
            query: Free-text search string. By convention Triage uses
                ``"Have we encountered <release_title>?"``.
            threshold: Minimum similarity in [0, 1]. Defaults to 0.85
                per DESIGN.md.

        Returns:
            List of fact dicts (possibly empty). Each entry has ``scope``,
            ``fact``, ``metadata``, and ``score``.
        """
        try:
            return self._backend.search(self.scope, query, threshold)
        except Exception as e:
            logger.warning("MemoryBankClient.search failed: %s", e)
            return []

    def add_fact(self, scope: str, fact: str, metadata: dict) -> None:
        """Persist a fact under ``scope`` with structured metadata.

        ``metadata["type"]`` should be ``"covered"`` (Editor) or
        ``"human-rejected"`` (Topic Gate) so Triage's filter recognizes it.
        Errors are logged and swallowed — failure to record is not worth
        crashing a pipeline run over (worst case: a duplicate).

        Args:
            scope: Memory Bank scope (typically ``"ai_release_pipeline"``).
            fact: Human-readable fact string.
            metadata: Structured metadata; must include ``type``.
        """
        try:
            self._backend.add_fact(scope, fact, metadata)
        except Exception as e:
            logger.warning("MemoryBankClient.add_fact failed: %s", e)


# --- Module-level tool functions (used by agents) ---------------------------

_default_client: Optional[MemoryBankClient] = None


def _client() -> MemoryBankClient:
    global _default_client
    if _default_client is None:
        _default_client = MemoryBankClient()
    return _default_client


def memory_bank_search(query: str, threshold: float = 0.85) -> list[dict]:
    """Search Memory Bank for facts matching ``query``.

    Triage tool. Returns an empty list when the candidate is novel. Each
    non-empty result includes ``metadata["type"]`` ∈ {"covered",
    "human-rejected"} so the agent can apply the design's hard-reject rule
    for human-rejected facts.

    Args:
        query: By convention ``"Have we encountered <release_title>?"``.
        threshold: Defaults to ``0.85`` per DESIGN.md.

    Returns:
        List of fact dicts with ``scope``, ``fact``, ``metadata``, ``score``.
    """
    return _client().search(query, threshold=threshold)


def memory_bank_add_fact(scope: str, fact: str, metadata: dict) -> None:
    """Add a fact to Memory Bank.

    Topic Gate writes ``type="human-rejected"`` on Skip; Editor writes
    ``type="covered"`` on Approve. Both go to scope ``"ai_release_pipeline"``.

    Args:
        scope: Memory Bank scope.
        fact: Human-readable fact string.
        metadata: Structured metadata; must include ``type``.
    """
    _client().add_fact(scope, fact, metadata)


def reset_default_client(client: Optional[MemoryBankClient] = None) -> None:
    """Test/dev helper: replace or clear the module-default client."""
    global _default_client
    _default_client = client


# --- Internal helpers -------------------------------------------------------


def _similarity(query: str, fact: str) -> float:
    """Token-overlap similarity in [0, 1]. Stand-in for embeddings."""
    q = _tokens(query)
    f = _tokens(fact)
    if not q or not f:
        return 0.0
    matched = q & f
    if not matched:
        return 0.0
    return max(len(matched) / len(q), len(matched) / len(f))


def _tokens(text: str) -> set[str]:
    return {
        t.lower() for t in _TOKEN_PATTERN.findall(text)
        if len(t) > 2 and t.lower() not in _STOPWORDS
    }
