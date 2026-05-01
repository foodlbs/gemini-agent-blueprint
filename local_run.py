"""Local exercise script for ai-release-pipeline-v2.

Run one polling cycle locally without staging deploy. Real:
  - 7 polling tools (ArXiv, GitHub Trending, RSS, HF Models, HF Papers,
    Hacker News, Anthropic news)
  - Vertex Gemini calls for Scout, Triage, and any downstream LLM agents
    that get reached
  - InMemoryMemoryService (no Vertex Memory Bank dependency)

Mocked (so no network / no cost / no side effects):
  - Telegram post helpers (no bot token / chat ID required)
  - Firestore lookup writes
  - Imagen, Veo, GCS upload (we don't generate or upload anything)
  - GitHub repo creation

Stops at:
  - First HITL pause (Topic Gate or Editor) — prints the would-be Telegram
    message and exits.
  - Triage SKIP terminal — prints the skip reason and exits.
  - 300-event cap — defensive (shouldn't ever hit this).

Run:

    PYTHONPATH=. uv run python local_run.py
"""

from __future__ import annotations

import asyncio
import logging
import os
from unittest.mock import MagicMock

# MUST be set before any tool module imports — tools.memory caches the backend.
os.environ.setdefault("MEMORY_BANK_BACKEND", "inmemory")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d %(levelname)5s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("local_run")


# ---------------------------------------------------------------------------
# Mock setup — replace external services with no-ops
# ---------------------------------------------------------------------------


def install_mocks() -> None:
    """Patch the external surfaces we don't want to hit during a local run."""

    # 1. Telegram: replace post helpers with logging stubs.
    from tools import telegram

    def fake_post_topic_approval(chosen, session_id, interrupt_id, user_id):
        log.info("=" * 60)
        log.info("[MOCK TELEGRAM] post_topic_approval would post:")
        log.info("  title:        %r", chosen.get("title"))
        log.info("  url:          %r", chosen.get("url"))
        log.info("  source:       %r", chosen.get("source"))
        log.info("  score:        %s", chosen.get("score"))
        log.info("  rationale:    %r", chosen.get("rationale", "")[:200])
        log.info("  callback_data Approve: %s",
                 telegram.callback_data(session_id, "approve", interrupt_id))
        log.info("  callback_data Skip:    %s",
                 telegram.callback_data(session_id, "skip", interrupt_id))
        log.info("=" * 60)
        return {"ok": True}

    def fake_post_editor_review(chosen, draft_preview, image_urls,
                                video_url, repo_url, session_id, interrupt_id,
                                user_id):
        log.info("=" * 60)
        log.info("[MOCK TELEGRAM] post_editor_review would post:")
        log.info("  title:         %r", chosen.get("title"))
        log.info("  draft preview: %r", (draft_preview or "")[:200])
        log.info("  images:        %d", len(image_urls))
        log.info("  video:         %s", video_url)
        log.info("  repo:          %s", repo_url)
        log.info("  interrupt_id:  %r", interrupt_id)
        log.info("=" * 60)
        return {"ok": True}

    telegram.post_topic_approval = fake_post_topic_approval
    telegram.post_editor_review = fake_post_editor_review

    # The HITL function nodes do `from tools.telegram import post_*` AT CALL
    # TIME (inside the generator), so our module-level patches above will
    # be picked up. Verify by inspection:
    import nodes.hitl as _hitl
    assert "from tools.telegram import" not in open(_hitl.__file__).read().split("\n", 30)[0:30], (
        "nodes/hitl.py changed import style — local mock won't be picked up"
    )

    # 2. Firestore: install a no-op mock client so _write_session_lookup
    # doesn't try to talk to GCP.
    fake_doc = MagicMock()
    fake_collection = MagicMock()
    fake_collection.document.return_value = fake_doc
    fake_client = MagicMock()
    fake_client.collection.return_value = fake_collection
    telegram.reset_firestore(fake_client)

    # 3. Imagen / Veo / GitHub / GCS: replace with mocks (only matter if
    # the cycle reaches that far — Triage skip / Topic Gate pause stops
    # us earlier).
    import tools.imagen
    import tools.veo
    import tools.gcs
    import tools.github_ops

    tools.imagen.generate_image = lambda **kw: b"FAKE_PNG"
    tools.veo.generate_video = lambda **kw: b"FAKE_MP4"
    tools.gcs.upload_to_gcs = lambda **kw: f"https://gcs-mock/{kw.get('slug', 'x')}"
    tools.github_ops.github_create_repo = lambda **kw: {"html_url": "https://github.com/mock/repo", "full_name": "mock/repo"}
    tools.github_ops.github_commit_files = lambda **kw: {"sha": "mock-sha-abc"}
    tools.github_ops.github_set_topics = lambda **kw: {"ok": True}

    log.info("Mocks installed: Telegram, Firestore, Imagen, Veo, GCS, GitHub.")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


async def main() -> int:
    install_mocks()

    # Imports go AFTER install_mocks so the mocked tool modules are picked up.
    from agent import root_agent
    from google.adk.runners import InMemoryRunner
    from google.genai import types as genai_types

    log.info(
        "Workflow: %s   edges=%d   graph nodes=%d",
        root_agent.name, len(root_agent.edges), len(root_agent.graph.nodes),
    )

    runner = InMemoryRunner(agent=root_agent, app_name="ai_release_pipeline_v2")
    sess = await runner.session_service.create_session(
        app_name="ai_release_pipeline_v2", user_id="local-exercise"
    )
    log.info("Session created: %s", sess.id)

    msg = genai_types.Content(
        role="user",
        parts=[genai_types.Part.from_text(text="Run a polling cycle.")],
    )

    paused = False
    interrupt_ids: set[str] = set()
    event_count = 0
    log.info("Streaming workflow events...")
    async for event in runner.run_async(
        user_id="local-exercise",
        session_id=sess.id,
        new_message=msg,
    ):
        event_count += 1
        long_running = getattr(event, "long_running_tool_ids", None) or set()
        if long_running:
            paused = True
            interrupt_ids.update(long_running)

        # Compact event log
        author = getattr(event, "author", "?")
        out = getattr(event, "output", None)
        out_repr = (str(out)[:120] + "…") if out and len(str(out)) > 120 else str(out)
        actions = getattr(event, "actions", None)
        route = getattr(actions, "route", None) if actions else None

        if route:
            log.info("event[%3d] %-22s ROUTE=%s output=%s", event_count, author, route, out_repr)
        elif out is not None:
            log.info("event[%3d] %-22s output=%s", event_count, author, out_repr)
        else:
            content = getattr(event, "content", None)
            text = ""
            if content and getattr(content, "parts", None):
                text = " ".join(getattr(p, "text", "") or "" for p in content.parts)
            if text:
                log.info("event[%3d] %-22s text=%r", event_count, author, text[:120])

        if event_count >= 300:
            log.warning("Event cap (300) reached, stopping.")
            break

    log.info("=" * 60)
    log.info("Run finished. paused=%s, total_events=%d", paused, event_count)
    if paused:
        log.info("interrupt_ids: %s", interrupt_ids)

    # Final state dump
    final = await runner.session_service.get_session(
        app_name="ai_release_pipeline_v2",
        user_id="local-exercise",
        session_id=sess.id,
    )
    log.info("=" * 60)
    log.info("FINAL STATE:")
    for k, v in dict(final.state).items():
        v_repr = str(v)[:300] + ("…" if len(str(v)) > 300 else "")
        log.info("  %-22s = %s", k, v_repr)

    return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
