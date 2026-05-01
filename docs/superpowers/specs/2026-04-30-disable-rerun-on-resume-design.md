# Disable `rerun_on_resume` on the v2 Workflow

**Date:** 2026-04-30
**Status:** Approved (path C from brainstorm — surgical fix first; Phase 2 architecture rework deferred)

## Problem

Each editor_request resume re-executes upstream graph nodes (writer loop +
asset stage), causing:

- Multiple editor Telegram messages per cycle (3–5 observed in repeated tests)
- `writer_iterations` climbing past the configured cap of 3 (observed: 4, 4, 5)
- `record_editor_verdict` never persisting `editor_verdict` to state — later
  workflow re-runs overwrite or skip it
- Drafts varying between editor messages (drafter is non-deterministic)
- Pipeline never reaches `publisher`; no `cycle_outcome` ever set

Empirical regression boundary across the session's smoke runs:

| Run | writer_iter | editor_iter | editor_verdict | Status  |
|---|---|---|---|---|
| post-iam-fix-smoke | 2 | 1 | approve | ✅ published |
| post-fix9-smoke | 2 | 1 | approve | ✅ |
| post-fix10-smoke | 2 | 1 | approve | ✅ |
| post-md-inject-smoke | 4 | None | None | ❌ |
| post-idempotent-smoke | 4 | None | None | ❌ |
| post-dict-safe-smoke | 5 | None | None | ❌ |
| post-crm-fix-smoke | 5 | None | None | ❌ (latest) |

The breakage is consistent across all post-md-inject runs and persists despite
fixes to dict-vs-model handling, IAM, idempotency, and Cloud Resource
Manager API enablement.

## Root cause

`google.adk.Workflow` defaults `rerun_on_resume=True`. On every resume from a
`RequestInput` pause, ADK re-enters the chain that led to the pause, repeating
work that has already completed:

- `drafter` runs again → produces a new draft
- `critic_llm` + `critic_split` run again → `writer_iterations` increments
- `image_asset_node` runs again → re-uploads images
- `editor_request` runs again → posts another Telegram message

The `record_editor_verdict` write that should follow the resume can be
clobbered by these re-runs, leaving `editor_verdict` `None` even after the
operator taps Approve.

The latest broken state's smoking gun is the contradiction:
`critic_verdict: revise` AND `image_assets count: 3` — image generation only
runs after an ACCEPT verdict, so seeing both means the pipeline ran the
writer loop AND the asset stage MORE THAN ONCE in the same session.

## Change

`agent.py`, single attribute on the root `Workflow`:

```python
root_agent = Workflow(
    name="ai_release_pipeline_v2",
    state_schema=PipelineState,
    rerun_on_resume=False,            # <-- ADD
    edges=[...],
)
```

That is the entire code change. No other file is touched.

## Verification plan

1. Apply the change, run `uv run pytest -q` (expect 161 passing).
2. `uv run python deploy.py` to push the engine update.
3. Trigger a fresh smoke with a new `user_id`:
   ```python
   engine.stream_query(user_id='post-rerun-fix-smoke', message=...)
   ```
4. Approve the topic_gate Telegram message (single tap).
5. **Acceptance criteria:**
   - Exactly **one** editor review message arrives (not 3–5).
   - `state["writer_iterations"] ≤ 3` at editor_request fire time.
6. Approve the editor message (single tap).
7. **Acceptance criteria:**
   - Exactly **one** `✅ Published` confirmation arrives within ~60 s.
   - `state["editor_iterations"] = 1`.
   - `state["editor_verdict"]["verdict"] == "approve"`.
   - `state["cycle_outcome"] == "published"`.
   - `state["asset_bundle_url"]` is a `gs://...` URL.

## Fallback (if A breaks resume entirely)

If `rerun_on_resume=False` causes the engine to never resume after a tap
(symptom: editor message arrives once but no state advances after the
operator taps Approve, no `editor_verdict` set, no `Published` message):

1. Revert the single-line change.
2. Apply Option C from the brainstorm:
   - `rerun_on_resume=False` on `drafter`, `critic_llm`, `critic_split`,
     `image_asset_node`, `video_asset_or_skip`, `gather_assets`
   - This preserves resume's ability to re-enter the immediate post-pause chain
     (`record_editor_verdict` → `route_editor_verdict` → `publisher`) while
     preventing the writer loop and asset stage from re-firing.

## Out of scope (Phase 2)

A separate spec — created after this fix is verified working in production —
will cover the SVG-canonical architecture rework:

- `LoopAgent(max_iterations=3)` wrapping the writer loop
- `ParallelAgent` for the researcher pool (docs / github / context)
- `ParallelAgent` for the asset stage (image / video)
- Restructure to remove the manual `writer_iterations` counter + sticky-key
  state hacks accumulated to work around the current edge-based loop

These are bigger refactors that should not block restoring the current
working state.

## Risk assessment

**Low.** Single-attribute change that's easily reverted. Worst case: resume
breaks and we roll back in under a minute, then implement the fallback (per-node
flag) in 5–10 minutes.
