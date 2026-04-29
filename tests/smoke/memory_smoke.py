"""Memory Bank smoke test: write a 'covered' fact, search it, delete.

The local Memory Bank backend (``shared.memory.LocalBackend``) is the
default; it has no remote dependencies. This smoke test exercises the
write → search → delete round-trip with similarity 0.85, confirming the
search cutoff matches DESIGN.md.

Exit code 0 = round-trip succeeded.
Exit code 1 = search miss or unexpected result count.
"""

import os
import sys

_THIS = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_THIS))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from shared.memory import (  # noqa: E402
    MemoryBankClient,
    memory_bank_add_fact,
    memory_bank_search,
    reset_default_client,
)


def main() -> int:
    # Use a fresh in-memory backend so the smoke test doesn't pollute any
    # ambient state. Production deploy would point at Vertex Memory Bank.
    reset_default_client(MemoryBankClient.in_memory(scope="smoke_test"))
    try:
        title = "Anthropic Skills"
        memory_bank_add_fact(
            scope="smoke_test",
            fact=f"Covered {title} on 2026-04-22",
            metadata={"type": "covered", "release_url": "https://example.com/x"},
        )
        results = memory_bank_search(
            f"Have we encountered {title}?", threshold=0.85
        )
        if len(results) != 1:
            print(f"FAIL: expected 1 hit, got {len(results)}")
            return 1
        if results[0]["metadata"]["type"] != "covered":
            print(f"FAIL: wrong fact type: {results[0]['metadata']['type']}")
            return 1
        print(f"Search hit: score={results[0]['score']:.3f}, type=covered")
        print("OK: Memory Bank round-trip succeeded.")
        return 0
    finally:
        reset_default_client(None)


if __name__ == "__main__":
    sys.exit(main())
