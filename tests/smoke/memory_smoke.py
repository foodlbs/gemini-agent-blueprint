"""Memory Bank smoke test for v2.

Two modes:

  - **inmemory** (default if MEMORY_BANK_BACKEND not set or =inmemory):
    runs offline against `InMemoryMemoryService`. Always available.
    No GCP dependencies.

  - **vertex** (MEMORY_BANK_BACKEND=vertex + GOOGLE_CLOUD_AGENT_ENGINE_ID=...):
    hits the real managed Vertex Memory Bank attached to the deployed
    ReasoningEngine. Validates the live round-trip.

Exit code 0 = round-trip succeeded. 1 = unexpected result count or
metadata round-trip failure.

Run::

    # Default offline (inmemory):
    PYTHONPATH=. uv run python tests/smoke/memory_smoke.py

    # Live Vertex Memory Bank (against a deployed engine):
    MEMORY_BANK_BACKEND=vertex \\
    GOOGLE_CLOUD_AGENT_ENGINE_ID=$(cat deploy/.deployed_resource_id | awk -F/ '{print $NF}') \\
    GOOGLE_CLOUD_PROJECT=gen-lang-client-0366435980 \\
    GOOGLE_CLOUD_LOCATION=us-west1 \\
    PYTHONPATH=. uv run python tests/smoke/memory_smoke.py
"""

import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_THIS))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# If MEMORY_BANK_BACKEND isn't set, default to inmemory so this smoke is
# always runnable without GCP credentials.
os.environ.setdefault("MEMORY_BANK_BACKEND", "inmemory")

from tools.memory import (  # noqa: E402
    DUPLICATE_SIMILARITY_THRESHOLD,
    memory_bank_add_fact,
    memory_bank_search,
    reset_default_service,
)


def main() -> int:
    backend = os.environ["MEMORY_BANK_BACKEND"]
    print(f"Backend: {backend}")
    if backend == "vertex" and not os.environ.get("GOOGLE_CLOUD_AGENT_ENGINE_ID"):
        print("SKIP: MEMORY_BANK_BACKEND=vertex but "
              "GOOGLE_CLOUD_AGENT_ENGINE_ID not set.")
        return 0

    reset_default_service(None)
    try:
        title = "Anthropic Skills SDK (smoke)"
        url   = "https://example.com/anthropic-skills-smoke"

        ok = memory_bank_add_fact(
            scope="ai_release_pipeline",
            fact=f"Covered: {title}",
            metadata={
                "type":           "covered",
                "release_url":    url,
                "release_source": "anthropic",
                "covered_at":     "2026-04-29T00:00:00Z",
            },
        )
        if not ok:
            print("FAIL: memory_bank_add_fact returned False")
            return 1

        results = memory_bank_search(f"Have we encountered {title}?")
        if len(results) < 1:
            print(f"FAIL: expected at least 1 hit, got {len(results)}")
            return 1

        # Check the metadata round-trip — Triage's hard-reject depends on it.
        hit = results[0]
        if hit["metadata"].get("type") != "covered":
            print(f"FAIL: metadata.type round-trip lost: got {hit['metadata']!r}")
            return 1
        if hit["score"] < DUPLICATE_SIMILARITY_THRESHOLD:
            # Note: VertexAi may use a different scoring scale; this is a
            # warning rather than a hard fail.
            print(
                f"WARN: top-hit score {hit['score']:.2f} below "
                f"DUPLICATE_SIMILARITY_THRESHOLD ({DUPLICATE_SIMILARITY_THRESHOLD})."
                " This may indicate the threshold needs re-calibration for "
                "the chosen backend."
            )

        print(
            f"OK: round-trip succeeded "
            f"(fact={hit['fact'][:60]!r}, score={hit['score']:.3f}, "
            f"type={hit['metadata'].get('type')})"
        )
        return 0
    finally:
        reset_default_service(None)


if __name__ == "__main__":
    sys.exit(main())
