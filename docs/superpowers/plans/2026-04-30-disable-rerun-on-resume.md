# Disable `rerun_on_resume` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `rerun_on_resume=False` to the root `Workflow` so resume from
`RequestInput` pauses doesn't re-execute upstream nodes — fixes duplicate
editor messages, runaway `writer_iterations`, and missing `editor_verdict`.

**Architecture:** Single one-line attribute change to `agent.py`. Verified by
(1) a unit test asserting the workflow attribute is set, (2) the existing 161
test suite passing unchanged, (3) a real smoke test against the deployed
engine asserting the regression symptoms are gone.

**Tech Stack:**
- google-adk 2.0.0b1 (Workflow / RequestInput)
- vertexai.agent_engines (deployed Reasoning Engine)
- pytest (unit tests)

---

## File Structure

| Path | Action | Purpose |
|---|---|---|
| `agent.py` | Modify | Add `rerun_on_resume=False` to root Workflow ctor |
| `tests/test_root_agent.py` | Create | Unit test asserting the attribute is set |
| `docs/superpowers/specs/2026-04-30-disable-rerun-on-resume-design.md` | Read-only | Source spec (no edits needed) |

The smoke verification doesn't get a test file — it's a one-shot operator
verification against a live deployed engine, run interactively with the
operator confirming Telegram message counts.

---

## Task 1: Add unit test asserting the Workflow attribute

**Files:**
- Create: `tests/test_root_agent.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_root_agent.py`:

```python
"""Test that the root_agent Workflow has rerun_on_resume=False so
resume from RequestInput pauses doesn't re-execute upstream nodes.

See docs/superpowers/specs/2026-04-30-disable-rerun-on-resume-design.md
for the symptoms this prevents (duplicate editor messages, runaway
writer_iterations, missing editor_verdict)."""

from agent import root_agent


def test_root_agent_disables_rerun_on_resume():
    """The default `Workflow(rerun_on_resume=True)` causes editor_request
    resumes to re-execute the writer loop + asset stage, producing
    duplicate Telegram messages and clobbering record_editor_verdict's
    state writes. We must explicitly disable it."""
    assert root_agent.rerun_on_resume is False, (
        "root_agent.rerun_on_resume must be False — see "
        "docs/superpowers/specs/2026-04-30-disable-rerun-on-resume-design.md"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run pytest tests/test_root_agent.py::test_root_agent_disables_rerun_on_resume -v`

Expected: FAIL with `AssertionError: root_agent.rerun_on_resume must be False`

(Reason: `Workflow.rerun_on_resume` defaults to `True` in `google.adk` —
the test will fail until we add the attribute in Task 2.)

---

## Task 2: Add `rerun_on_resume=False` to root_agent

**Files:**
- Modify: `agent.py:60-65` (the `Workflow(...)` constructor call)

- [ ] **Step 1: Read current `agent.py` constructor**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && grep -n "root_agent = Workflow" agent.py`

Expected: a line number near 60 like `60:root_agent = Workflow(`

- [ ] **Step 2: Apply the one-line change**

Use the Edit tool to change:

```python
root_agent = Workflow(
    name="ai_release_pipeline_v2",
    state_schema=PipelineState,
    edges=[
```

To:

```python
root_agent = Workflow(
    name="ai_release_pipeline_v2",
    state_schema=PipelineState,
    rerun_on_resume=False,            # See docs/superpowers/specs/2026-04-30-disable-rerun-on-resume-design.md
    edges=[
```

- [ ] **Step 3: Run the unit test to verify it passes**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run pytest tests/test_root_agent.py::test_root_agent_disables_rerun_on_resume -v`

Expected: PASS

- [ ] **Step 4: Run the full test suite to verify no regression**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run pytest -q`

Expected: `162 passed, 2 warnings` (was 161; we added 1 new test)

- [ ] **Step 5: Commit**

```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
git add agent.py tests/test_root_agent.py && \
git commit -m "$(cat <<'EOF'
fix: disable rerun_on_resume on root Workflow

Each editor_request resume was re-executing the writer loop + asset
stage, causing duplicate Telegram messages, writer_iterations climbing
past the cap, and record_editor_verdict's state writes being clobbered.

See docs/superpowers/specs/2026-04-30-disable-rerun-on-resume-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: Commit succeeds.

---

## Task 3: Deploy the engine update

**Files:** none (deploy.py invokes Vertex SDK)

- [ ] **Step 1: Verify .env has GOOGLE_CLOUD_PROJECT**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && grep -E "^GOOGLE_CLOUD_PROJECT=" .env`

Expected: `GOOGLE_CLOUD_PROJECT=gen-lang-client-0366435980`

- [ ] **Step 2: Deploy**

Run:
```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
set -a && source .env && set +a && \
uv run python deploy.py 2>&1 | tail -5
```

Expected output ends with:
```
Wrote deploy/.deployed_resource_id

Resource: projects/988979702911/locations/us-west1/reasoningEngines/2525375898861961216
```

(Takes ~2-5 minutes for `engine.update()` to complete server-side.)

---

## Task 4: Smoke test — trigger fresh cycle, pause at topic_gate

**Files:** none (interactive smoke against deployed engine)

- [ ] **Step 1: Wait 15s for engine update propagation, then trigger fresh smoke**

Run:
```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
sleep 15 && \
uv run python -c "
import vertexai
from vertexai import agent_engines
vertexai.init(project='gen-lang-client-0366435980', location='us-west1')
engine = agent_engines.get(resource_name='projects/988979702911/locations/us-west1/reasoningEngines/2525375898861961216')
saw_pause = False
event_count = 0
for event in engine.stream_query(
    user_id='post-rerun-fix-smoke',
    message={'role':'user','parts':[{'text':'Run a polling cycle.'}]},
):
    event_count += 1
    if isinstance(event, dict) and event.get('long_running_tool_ids'):
        saw_pause = True
    if event_count >= 30:
        break
print(f'events={event_count} pause={saw_pause}')
"
```

Expected output:
```
events=10  (or similar small number, ≤ 14)
pause=True
```

If `pause=False`, scout_split parsed 0 candidates (intermittent Scout issue)
— retry with a different user_id (`post-rerun-fix-smoke-2`).

---

## Task 5: Operator approves topic_gate, observes single editor message

**Files:** none

- [ ] **Step 1: Operator taps Approve on the topic_gate Telegram message**

Tell the operator: "Tap Approve on the newest topic_gate message in your
Telegram chat. Wait 3-5 minutes for the editor review .md attachment to
arrive."

- [ ] **Step 2: Verify exactly ONE editor message arrives**

Ask the operator: "How many editor review messages arrived in your chat
since the topic_gate Approve?"

**Acceptance:** Exactly 1 message.

If 2 or more: Option A failed. Skip to Task 8 (fallback).
If 0 after 8 minutes: Engine error — check logs (Task 8 fallback diagnosis).
If 1: Proceed.

- [ ] **Step 3: Verify state shows clean writer loop**

Run:
```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
uv run python -c "
import vertexai
from vertexai import agent_engines
vertexai.init(project='gen-lang-client-0366435980', location='us-west1')
engine = agent_engines.get(resource_name='projects/988979702911/locations/us-west1/reasoningEngines/2525375898861961216')
sessions = engine.list_sessions(user_id='post-rerun-fix-smoke').get('sessions', [])
s = sessions[0]
full = engine.get_session(user_id='post-rerun-fix-smoke', session_id=s['id'])
state = full.get('state', {})
print(f'writer_iterations: {state.get(\"writer_iterations\")}')
print(f'image_assets count: {len(state.get(\"image_assets\") or [])}')
print(f'critic_verdict:    {state.get(\"critic_verdict\")}')
"
```

**Acceptance:**
- `writer_iterations` ≤ 3 (proves the writer loop didn't over-run)
- `image_assets count` ≥ 1 (image generation succeeded)
- `critic_verdict` is `accept` (not `revise`)

If `writer_iterations > 3` OR `critic_verdict == "revise"` while assets are
populated: Option A failed structurally. Skip to Task 8.

---

## Task 6: Operator approves editor, observes Published confirmation

**Files:** none

- [ ] **Step 1: Operator taps Approve on the editor `.md` Telegram message**

Tell the operator: "Tap Approve on the editor review message. Wait ~30-60s
for the final ✅ Published confirmation to arrive."

- [ ] **Step 2: Verify exactly ONE Published confirmation**

Ask the operator: "Did you receive the ✅ Published message? How many?"

**Acceptance:** Exactly 1 `✅ Published` message.

- [ ] **Step 3: Verify cycle reached published state**

Run:
```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
uv run python -c "
import vertexai
from vertexai import agent_engines
vertexai.init(project='gen-lang-client-0366435980', location='us-west1')
engine = agent_engines.get(resource_name='projects/988979702911/locations/us-west1/reasoningEngines/2525375898861961216')
sessions = engine.list_sessions(user_id='post-rerun-fix-smoke').get('sessions', [])
s = sessions[0]
full = engine.get_session(user_id='post-rerun-fix-smoke', session_id=s['id'])
state = full.get('state', {})
ev = state.get('editor_verdict') or {}
ev_v = ev.get('verdict') if isinstance(ev, dict) else getattr(ev, 'verdict', None)
print(f'editor_iterations: {state.get(\"editor_iterations\")}')
print(f'editor_verdict.verdict: {ev_v}')
print(f'cycle_outcome: {state.get(\"cycle_outcome\")}')
print(f'asset_bundle_url: {state.get(\"asset_bundle_url\")}')
"
```

**Acceptance:**
- `editor_iterations: 1`
- `editor_verdict.verdict: approve`
- `cycle_outcome: published`
- `asset_bundle_url: gs://...` (a real URL)

---

## Task 7: Mark task complete

**Files:** none

- [ ] **Step 1: Tag the verified deploy in git**

Run:
```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
git tag -a v2-rerun-on-resume-fixed -m "Verified single editor message + Published cycle on $(date '+%Y-%m-%d')"
```

Expected: Tag created.

- [ ] **Step 2: Commit any straggler changes (if any)**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && git status`

If clean, no action. If dirty, commit relevant changes.

---

## Task 8 (fallback): Per-node `rerun_on_resume=False`

**Only execute if Task 5 or Task 6 acceptance fails.**

**Files:**
- Modify: `agent.py` — revert root Workflow change, add per-node attributes
- Modify: `agents/writer.py`, `agents/researchers.py` — set
  `rerun_on_resume=False` on individual LlmAgents

- [ ] **Step 1: Revert the root Workflow change**

In `agent.py`, remove the `rerun_on_resume=False,` line from the `Workflow(...)`
constructor (back to the default `True`).

- [ ] **Step 2: Apply per-node `rerun_on_resume=False` on writer-loop agents**

Modify `agents/writer.py`:

```python
drafter = Agent(
    name="drafter",
    model="gemini-2.5-pro",
    instruction=DRAFTER_INSTRUCTION,
    output_key="draft",
    rerun_on_resume=False,  # see disable-rerun-on-resume-design.md fallback
)


critic_llm = Agent(
    name="critic_llm",
    model="gemini-2.5-flash-lite",
    instruction=CRITIC_INSTRUCTION,
    output_key="critic_raw",
    rerun_on_resume=False,
)
```

Function nodes don't have a `rerun_on_resume` attribute as plain callables —
the writer-loop's `critic_split`, `image_asset_node`, `video_asset_or_skip`,
and `gather_assets` get the same flag set on the Workflow that wraps them.
For now, Phase-2 architecture rework (LoopAgent) is the cleaner answer for
function-node loop control.

- [ ] **Step 3: Update the unit test**

Modify `tests/test_root_agent.py` to assert per-node attributes instead of the
root Workflow attribute (since we reverted root):

```python
from agent import root_agent
from agents.writer import drafter, critic_llm


def test_writer_agents_disable_rerun_on_resume():
    """Fallback (Option C in the spec): root Workflow has the default
    rerun_on_resume=True; individual writer-loop agents are flagged off."""
    assert drafter.rerun_on_resume is False
    assert critic_llm.rerun_on_resume is False
```

Delete the previous root-level test.

- [ ] **Step 4: Run full test suite**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run pytest -q`

Expected: All tests pass.

- [ ] **Step 5: Re-deploy and re-smoke**

Repeat Tasks 3-6 with `user_id='post-rerun-fix-fallback-smoke'`.

- [ ] **Step 6: Commit**

```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
git add agent.py agents/writer.py tests/test_root_agent.py && \
git commit -m "fix: per-node rerun_on_resume=False (fallback from root-level approach)

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```
