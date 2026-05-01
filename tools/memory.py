"""Memory Bank adapter — see DESIGN.v2.md §7.2 + §9.

Exposes two sync functions the rest of the pipeline calls:

  - ``memory_bank_search(query, scope, limit) -> list[dict]``
  - ``memory_bank_add_fact(scope, fact, metadata) -> bool``

Backend selection is env-driven (``MEMORY_BANK_BACKEND``):

  - ``inmemory``   →  ``InMemoryMemoryService``  (tests + local dev)
  - ``vertex``     →  ``VertexAiMemoryBankService`` (production default)

The ADK memory services expose ``async`` methods. This module wraps them
into sync calls because (a) the design's public API is sync, and
(b) the function nodes that call ``memory_bank_add_fact`` are sync.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import os
import re
import uuid
from typing import Any, Optional

from google.adk.events.event import Event
from google.adk.memory import InMemoryMemoryService, VertexAiMemoryBankService
from google.adk.memory.base_memory_service import BaseMemoryService
from google.adk.sessions import Session
from google.genai import types as genai_types

logger = logging.getLogger(__name__)


# Per DESIGN.v2.md §9.3. Tunable, but inherited from v1's calibration.
DUPLICATE_SIMILARITY_THRESHOLD = 0.85


# ---------------------------------------------------------------------------
# Backend factory (cached singleton; reset_default_service() for tests)
# ---------------------------------------------------------------------------


_service_singleton: Optional[BaseMemoryService] = None


def _get_memory_service() -> BaseMemoryService:
    """Return the configured backend; cache after first call."""
    global _service_singleton
    if _service_singleton is None:
        _service_singleton = _build_service()
    return _service_singleton


def _build_service() -> BaseMemoryService:
    backend = os.environ.get("MEMORY_BANK_BACKEND", "vertex")
    if backend == "inmemory":
        return InMemoryMemoryService()
    if backend == "vertex":
        # Memory Bank in ADK 2.0 is attached to the ReasoningEngine
        # itself — there is no separate "memory bank" resource. The
        # service routes API calls to /reasoningEngines/{id}/memories.
        # Inside Agent Runtime, GOOGLE_CLOUD_AGENT_ENGINE_ID is auto-set;
        # locally, the operator sets it to the deployed engine's ID for
        # staging tests (`MEMORY_BANK_BACKEND=inmemory` for unit tests).
        agent_engine_id = os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID")
        if not agent_engine_id:
            raise RuntimeError(
                "GOOGLE_CLOUD_AGENT_ENGINE_ID must be set when "
                "MEMORY_BANK_BACKEND=vertex. Auto-set inside Agent Runtime; "
                "for tests use MEMORY_BANK_BACKEND=inmemory."
            )
        # Accept either a bare ID ('456') or a full resource path
        # ('projects/.../reasoningEngines/456') — strip to the bare ID
        # because that's what the constructor expects.
        if "/" in agent_engine_id:
            agent_engine_id = agent_engine_id.split("/")[-1]
        return VertexAiMemoryBankService(
            project=os.environ.get("GOOGLE_CLOUD_PROJECT"),
            location=os.environ.get("GOOGLE_CLOUD_LOCATION"),
            agent_engine_id=agent_engine_id,
        )
    raise ValueError(f"Unknown MEMORY_BANK_BACKEND: {backend!r}")


def reset_default_service(service: Optional[BaseMemoryService] = None) -> None:
    """Override or clear the cached singleton. Tests use this to inject mocks."""
    global _service_singleton
    _service_singleton = service


# ---------------------------------------------------------------------------
# Sync↔async bridge
# ---------------------------------------------------------------------------


def _run_async(coro):
    """Run an async coroutine to completion, regardless of caller's loop state.

    - If no event loop is running: ``asyncio.run`` directly.
    - If a loop IS running (e.g. inside an ADK Workflow):
      submit to a thread-pool that creates its own fresh loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Fallback: we're inside a running loop. Run in a worker thread.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=60)


# ---------------------------------------------------------------------------
# Metadata encoding contract
# ---------------------------------------------------------------------------
#
# The ADK memory services ingest Sessions and surface back ``MemoryEntry``
# objects whose shape varies between backends. To make metadata round-trip
# reliable across InMemory + VertexAi, we encode the metadata dict into the
# fact text itself as a trailing HTML comment:
#
#     {fact_text}
#     <!-- airel_metadata: {"type": "human-rejected", "release_url": "..."} -->
#
# ``memory_bank_search`` parses the comment back into a ``metadata`` dict and
# strips it from the human-readable ``fact`` field before returning.

# Match the comment block by structure (any content between the markers).
# The JSON body inside is parsed separately so we tolerate corrupt metadata
# without leaving the comment glued to the human-readable fact text.
_METADATA_BLOCK_RE = re.compile(
    r"\s*<!--\s*airel_metadata:\s*(.*?)\s*-->\s*$",
    re.DOTALL,
)


def _encode_fact_with_metadata(fact: str, metadata: dict) -> str:
    """Append a metadata HTML comment so the round-trip survives any backend."""
    payload = json.dumps(metadata, default=str, sort_keys=True)
    return f"{fact}\n<!-- airel_metadata: {payload} -->"


def _decode_fact(text: str) -> tuple[str, dict]:
    """Extract (clean_fact, metadata_dict) from a stored fact string.

    If the comment block is present but the JSON inside is corrupt, the
    comment is still stripped and an empty metadata dict is returned —
    we don't leak the corrupt comment into Triage's view.
    """
    match = _METADATA_BLOCK_RE.search(text)
    if not match:
        return text.strip(), {}
    metadata: dict = {}
    try:
        parsed = json.loads(match.group(1))
        if isinstance(parsed, dict):
            metadata = parsed
    except (ValueError, TypeError):
        pass
    clean = _METADATA_BLOCK_RE.sub("", text).rstrip()
    return clean, metadata


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def memory_bank_search(
    query: str,
    scope: str = "ai_release_pipeline",
    limit: int = 5,
) -> list[dict]:
    """Search Memory Bank for facts similar to ``query``.

    Returns a list of dicts with keys ``fact`` (str), ``score`` (float
    0..1), ``metadata`` (dict). Sorted by ``score`` desc; capped at
    ``limit``. Returns ``[]`` on any error (Triage prefers false positives
    over false negatives — see §9.3 + §12.3).
    """
    try:
        service = _get_memory_service()
        response = _run_async(service.search_memory(
            app_name=scope, user_id="pipeline", query=query,
        ))
    except Exception as e:
        logger.warning("memory_bank_search failed: %s", e)
        return []

    memories = getattr(response, "memories", None) or []
    out: list[dict] = []
    for m in memories:
        text = _extract_text(m)
        if not text:
            continue
        clean_fact, metadata = _decode_fact(text)
        score = _extract_score(m)
        out.append({"fact": clean_fact, "score": score, "metadata": metadata})

    out.sort(key=lambda r: r["score"], reverse=True)
    return out[:limit]


def memory_bank_add_fact(scope: str, fact: str, metadata: dict) -> bool:
    """Persist a fact to Memory Bank.

    ``metadata`` MUST include ``type`` ∈ {``"covered"``, ``"human-rejected"``}
    AND ``release_url`` AND ``release_source``. Other keys are free-form
    (Publisher adds ``bundle_url`` and ``starter_repo``; record_topic_verdict
    adds ``rejected_at``).

    Returns True on success, False on transport error. Raises ValueError on
    schema violations (caller bug, not a runtime fault).
    """
    if not metadata.get("type"):
        raise ValueError(
            "metadata['type'] is required. Expected 'covered' or 'human-rejected'."
        )
    if metadata["type"] not in ("covered", "human-rejected"):
        raise ValueError(
            f"metadata['type'] must be 'covered' or 'human-rejected', "
            f"got {metadata['type']!r}"
        )
    if not metadata.get("release_url"):
        raise ValueError("metadata['release_url'] is required")
    if not metadata.get("release_source"):
        raise ValueError("metadata['release_source'] is required")

    encoded_fact = _encode_fact_with_metadata(fact, metadata)
    try:
        service = _get_memory_service()
        session = _build_synthetic_session(scope=scope, fact_text=encoded_fact)
        _run_async(service.add_session_to_memory(session))
        return True
    except Exception as e:
        logger.error("memory_bank_add_fact failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Helpers — extract text + score from heterogeneous memory result types
# ---------------------------------------------------------------------------


def _extract_text(memory_entry: Any) -> str:
    """Best-effort: surface the fact string from a MemoryEntry-like object."""
    # Common shapes across ADK 2.0 betas:
    #   - object with .content : Content (parts=[Part(text=...)])
    #   - object with .memory : str
    #   - object with .text : str
    #   - dict-like
    content = getattr(memory_entry, "content", None)
    if content is not None and getattr(content, "parts", None):
        return " ".join(
            (getattr(p, "text", "") or "")
            for p in content.parts
        ).strip()
    for attr in ("memory", "text", "fact"):
        v = getattr(memory_entry, attr, None)
        if isinstance(v, str) and v:
            return v
    if isinstance(memory_entry, dict):
        return str(
            memory_entry.get("memory")
            or memory_entry.get("text")
            or memory_entry.get("fact")
            or ""
        )
    return ""


def _extract_score(memory_entry: Any) -> float:
    """Best-effort similarity score; default 1.0 if backend doesn't expose one."""
    for attr in ("score", "similarity", "relevance"):
        v = getattr(memory_entry, attr, None)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    if isinstance(memory_entry, dict):
        v = memory_entry.get("score")
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    return 1.0


def _build_synthetic_session(scope: str, fact_text: str) -> Session:
    """One-event Session whose user content carries the encoded fact."""
    event = Event(
        invocation_id=str(uuid.uuid4()),
        author="user",
        content=genai_types.Content(
            role="user",
            parts=[genai_types.Part.from_text(text=fact_text)],
        ),
    )
    return Session(
        app_name=scope,
        user_id="pipeline",
        id=str(uuid.uuid4()),
        events=[event],
    )
