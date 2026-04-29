"""Live smoke test for tools/pollers — hits real APIs, no mocks.

Runs every poller with a 7-day cutoff and prints per-source candidate
counts plus a sample title, so you can see at a glance which sources are
healthy. Also exercises the LLM call path by passing ``since`` as an ISO
8601 string (the shape the agent passes through ADK).

Usage::

    uv run python tests/smoke/pollers_smoke.py

Exits non-zero if fewer than ``MIN_HEALTHY_SOURCES`` distinct sources
returned at least one candidate — the goal is "at least 10 sources
functional" per the deploy review.
"""

from __future__ import annotations

import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from tools.pollers import (
    RSS_FEEDS,
    poll_anthropic_news,
    poll_arxiv,
    poll_github_trending,
    poll_hackernews_ai,
    poll_hf_models,
    poll_hf_papers,
    poll_rss,
)

# A "source" in this report is an individual upstream (one URL or one API
# endpoint), not a poller function — poll_rss alone covers many sources.
MIN_HEALTHY_SOURCES = 10
LOOKBACK_DAYS = 7

POLLERS = [
    ("poll_arxiv", poll_arxiv),
    ("poll_github_trending", poll_github_trending),
    ("poll_hf_models", poll_hf_models),
    ("poll_hf_papers", poll_hf_papers),
    ("poll_hackernews_ai", poll_hackernews_ai),
    ("poll_anthropic_news", poll_anthropic_news),
    ("poll_rss", poll_rss),
]


def main() -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    since_iso = cutoff.isoformat().replace("+00:00", "Z")

    print(f"Cutoff: {since_iso}  ({LOOKBACK_DAYS} days back)")
    print(f"Configured RSS feeds: {len(RSS_FEEDS)}")
    print(f"All pollers: {[name for name, _ in POLLERS]}")
    print()

    by_source: defaultdict[str, list[dict]] = defaultdict(list)
    poller_status: dict[str, str] = {}

    for name, fn in POLLERS:
        t0 = time.time()
        try:
            results = fn(since_iso)
        except Exception as e:
            poller_status[name] = f"EXCEPTION ({type(e).__name__}): {e}"
            continue
        elapsed = time.time() - t0
        for item in results:
            by_source[item["source"]].append(item)
        poller_status[name] = (
            f"{'OK' if results else 'EMPTY'}  count={len(results)}  {elapsed:0.1f}s"
        )

    print("=== Poller status ===")
    for name, status in poller_status.items():
        print(f"  {name:25s} {status}")

    print()
    print(f"=== Sources observed (cutoff={LOOKBACK_DAYS}d): {len(by_source)} ===")
    for source in sorted(by_source.keys()):
        items = by_source[source]
        sample = items[0]["title"][:80] if items else ""
        print(f"  {source:22s} count={len(items):4d}  e.g. {sample}")

    healthy = sum(1 for items in by_source.values() if items)
    print()
    print(f"Healthy sources (>=1 candidate): {healthy}")
    print(f"Threshold: {MIN_HEALTHY_SOURCES}")

    if healthy < MIN_HEALTHY_SOURCES:
        print(f"FAIL: only {healthy}/{MIN_HEALTHY_SOURCES} sources returned data.")
        return 1
    print("PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
