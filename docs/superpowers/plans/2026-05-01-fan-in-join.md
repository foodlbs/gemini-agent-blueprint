# Fan-In Join Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `gather_research` a true graph join (`JoinFunctionNode` with `wait_for_output=True` + state counter) so it fires once after all 3 researchers complete instead of 3 times — eliminating duplicate editor Telegram messages and unbounded writer-loop cascades.

**Architecture:** New `nodes/_join_node.py` defines a `JoinFunctionNode(FunctionNode)` Pydantic subclass with `wait_for_output: bool = True`. `nodes/aggregation.py` splits `gather_research` into a counter-gated `_gather_research_impl` function plus a `JoinFunctionNode` instance with the same name. `shared/models.py` adds a `gather_research_call_count: int = 0` field to `PipelineState`. `agent.py` is unchanged. Pytest gates pre-deploy; smoke acceptance gates post-deploy.

**Tech Stack:**
- google-adk 2.0.0b1 (FunctionNode subclass + wait_for_output)
- pydantic 2.x (PipelineState field, JoinFunctionNode subclass)
- pytest (unit + graph-shape regression tests)
- vertexai.agent_engines (smoke against deployed Reasoning Engine)

---

## File Structure

| Path | Action | Purpose |
|---|---|---|
| `nodes/_join_node.py` | Create | `JoinFunctionNode(FunctionNode)` subclass with `wait_for_output=True`. ~10 LOC. |
| `tests/test_join_node.py` | Create | Unit test asserting `JoinFunctionNode` defaults. |
| `shared/models.py` | Modify | Add `gather_research_call_count: int = 0` to `PipelineState` (matches existing `chosen_release_write_count` convention at line 178). |
| `nodes/aggregation.py` | Modify | Split `gather_research` into `_gather_research_impl` (counter-gated) + `gather_research = JoinFunctionNode(func=...)` instance. `gather_assets` unchanged. |
| `tests/test_aggregation.py` | Create | Three unit tests for `_gather_research_impl` counter behavior. |
| `tests/test_graph_shape.py` | Create | Regression guard: walks `root_agent.graph.edges`, asserts no node has > 1 unconditional incoming edge unless it's a `JoinFunctionNode`. |
| `agent.py` | Unchanged | Imports `gather_research` from `nodes.aggregation` exactly as before. |
| `docs/superpowers/specs/2026-05-01-fan-in-join-design.md` | Read-only | Source spec. |

---

## Task 1: Create `JoinFunctionNode` primitive (TDD)

**Files:**
- Create: `nodes/_join_node.py`
- Create: `tests/test_join_node.py`

- [ ] **Step 1: Verify ADK source exposes `wait_for_output` as a settable Pydantic field**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && grep -n "wait_for_output" .venv/lib/python3.12/site-packages/google/adk/workflow/_base_node.py`

Expected output includes:
```
65:  wait_for_output: bool = False
```

Then run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && grep -n "model_config" .venv/lib/python3.12/site-packages/google/adk/workflow/_base_node.py`

Expected: a `ConfigDict(arbitrary_types_allowed=True)` line — confirming the model is NOT frozen (so subclasses can override field defaults). Cite this in the commit message.

- [ ] **Step 2: Write the failing test**

Create `tests/test_join_node.py` with this exact content:

```python
"""Unit test for JoinFunctionNode — see
docs/superpowers/specs/2026-05-01-fan-in-join-design.md."""

from google.adk import Context, Event

from nodes._join_node import JoinFunctionNode


def test_join_function_node_defaults_wait_for_output_true():
    """A JoinFunctionNode must have wait_for_output=True so it stays
    WAITING after returning a no-output Event, allowing predecessors
    to re-trigger it. See ADK _base_node.py:65-74 for the contract."""
    def _noop(node_input, ctx: Context) -> Event:
        return Event()

    node = JoinFunctionNode(func=_noop, name="test_join")
    assert node.wait_for_output is True
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run pytest tests/test_join_node.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'nodes._join_node'`.

- [ ] **Step 4: Create `nodes/_join_node.py`**

Create `nodes/_join_node.py` with this exact content:

```python
"""JoinFunctionNode — a FunctionNode preconfigured for graph fan-in joins.

A node with multiple unconditional incoming edges (true fan-in) must use
this subclass instead of a plain function, otherwise each predecessor's
completion independently triggers the function and cascades downstream
once per predecessor (see post-md-inject regression diagnosed in
docs/superpowers/specs/2026-05-01-fan-in-join-design.md).

Mechanism: ADK's `BaseNode.wait_for_output=True` keeps the node in WAITING
state when its function returns an Event with no output, allowing
predecessors to re-trigger it. The function decides when "all inputs
ready" by returning Event(output=...) — typically gated by a counter or
state-key presence check.

See ADK _base_node.py:65-74 for the wait_for_output contract.
"""

from google.adk.workflow import FunctionNode


class JoinFunctionNode(FunctionNode):
    """FunctionNode with wait_for_output=True. Use for nodes with multiple
    unconditional incoming edges in the workflow graph."""
    wait_for_output: bool = True
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run pytest tests/test_join_node.py -v`

Expected: `1 passed`.

- [ ] **Step 6: Run full suite to confirm no regression**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run pytest -q 2>&1 | tail -3`

Expected: `162 passed` (was 161; we added 1 new test).

- [ ] **Step 7: Commit**

```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
git add nodes/_join_node.py tests/test_join_node.py && \
git commit -m "$(cat <<'EOF'
feat: JoinFunctionNode primitive for graph fan-in joins

Pydantic subclass of FunctionNode with wait_for_output=True. Used for
nodes with multiple unconditional incoming edges (true fan-in) so they
stay WAITING until their function explicitly yields output.

Verified against ADK source:
.venv/lib/python3.12/site-packages/google/adk/workflow/_base_node.py:65
(wait_for_output: bool = False) — settable via Pydantic field assignment;
model_config has no frozen=True.

See docs/superpowers/specs/2026-05-01-fan-in-join-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: Commit succeeds.

---

## Task 2: Add `gather_research_call_count` field to `PipelineState`

**Files:**
- Modify: `shared/models.py:178` (insert near existing `chosen_release_write_count`)

- [ ] **Step 1: Locate the insertion point**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && grep -n "chosen_release_write_count" shared/models.py`

Expected: a line number near 178.

- [ ] **Step 2: Insert the new field**

Use the Edit tool to add `gather_research_call_count: int = 0` to `PipelineState`. Find this section in `shared/models.py`:

```python
    research: Optional[ResearchDossier] = None
    """Merged dossier produced by gather_research from the three above."""
```

Replace with:

```python
    research: Optional[ResearchDossier] = None
    """Merged dossier produced by gather_research from the three above."""
    gather_research_call_count: int = 0
    """Counter incremented by `gather_research` on each predecessor trigger.
    Once it reaches 3 (one per researcher), the join proceeds and yields
    output. See docs/superpowers/specs/2026-05-01-fan-in-join-design.md."""
```

- [ ] **Step 3: Run full suite to confirm no regression**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run pytest -q 2>&1 | tail -3`

Expected: `162 passed` (no new test added in this task; the field is exercised by Task 3).

- [ ] **Step 4: Commit**

```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
git add shared/models.py && \
git commit -m "$(cat <<'EOF'
feat: add gather_research_call_count to PipelineState

Counter field used by the upcoming gather_research join refactor.
Type and default match the existing chosen_release_write_count pattern
(int = 0) so state.get(key, 0) + 1 always works without None-handling.

See docs/superpowers/specs/2026-05-01-fan-in-join-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: Commit succeeds.

---

## Task 3: Refactor `gather_research` into counter-gated join (TDD)

**Files:**
- Modify: `nodes/aggregation.py` (split `gather_research` into impl + JoinFunctionNode)
- Create: `tests/test_aggregation.py`

- [ ] **Step 1: Write the three failing tests**

Create `tests/test_aggregation.py` with this exact content:

```python
"""Unit tests for nodes/aggregation.gather_research — counter-gated join.

See docs/superpowers/specs/2026-05-01-fan-in-join-design.md."""

from types import SimpleNamespace

from nodes.aggregation import _gather_research_impl


def _stub_ctx(state=None):
    """Minimal Context stub — _gather_research_impl only reads ctx.state."""
    return SimpleNamespace(state=state if state is not None else {})


# Realistic researcher payloads (raw JSON strings, as ADK output_key writes them).
_DOCS_RAW = '{"summary": "docs summary"}'
_GH_RAW = (
    '{"summary": "github summary",'
    ' "repo_meta": {"stars": 10, "forks": 1},'
    ' "readme_excerpt": "RE",'
    ' "file_list": ["README.md"]}'
)
_CONTEXT_RAW = (
    '{"summary": "context summary",'
    ' "reactions": ["+1"],'
    ' "related_releases": ["r-1"]}'
)


def _seed_state():
    return {
        "docs_research":    _DOCS_RAW,
        "github_research":  _GH_RAW,
        "context_research": _CONTEXT_RAW,
    }


def test_gather_research_returns_no_output_on_first_call():
    """First trigger increments counter to 1; node must stay WAITING
    (Event with no output) so ADK re-triggers it on the next predecessor."""
    ctx = _stub_ctx(state=_seed_state())
    result = _gather_research_impl(node_input=None, ctx=ctx)
    assert result.output is None
    assert ctx.state["gather_research_call_count"] == 1
    assert "research" not in ctx.state


def test_gather_research_returns_no_output_on_second_call():
    """Second trigger increments counter to 2; still WAITING."""
    ctx = _stub_ctx(state={**_seed_state(), "gather_research_call_count": 1})
    result = _gather_research_impl(node_input=None, ctx=ctx)
    assert result.output is None
    assert ctx.state["gather_research_call_count"] == 2
    assert "research" not in ctx.state


def test_gather_research_yields_merged_dossier_on_third_call():
    """Third trigger advances counter to 3 → join proceeds: output present
    AND state['research'] is the merged ResearchDossier."""
    ctx = _stub_ctx(state={**_seed_state(), "gather_research_call_count": 2})
    result = _gather_research_impl(node_input=None, ctx=ctx)
    assert ctx.state["gather_research_call_count"] == 3
    # Output is non-None (the sections_filled dict).
    assert result.output is not None
    assert "sections_filled" in result.output
    # Merged dossier landed in state.
    merged = ctx.state["research"]
    assert merged is not None
    assert merged.summary == "docs summary"  # docs wins precedence
    assert merged.repo_meta == {"stars": 10, "forks": 1}
    assert merged.reactions == ["+1"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run pytest tests/test_aggregation.py -v`

Expected: All 3 tests FAIL with `ImportError: cannot import name '_gather_research_impl' from 'nodes.aggregation'`.

- [ ] **Step 3: Refactor `nodes/aggregation.py`**

Find this current content in `nodes/aggregation.py` (around lines 68-91):

```python
def gather_research(node_input, ctx: Context) -> Event:
    """§6.4.4 — parse + merge docs/github/context dossiers into `research`."""
    docs    = _parse_dossier(ctx.state.get("docs_research"),    "docs")
    gh      = _parse_dossier(ctx.state.get("github_research"),  "github")
    context = _parse_dossier(ctx.state.get("context_research"), "context")

    merged = ResearchDossier(
        # docs_researcher owns these
        summary          = docs.summary or context.summary or gh.summary,
        headline_quotes  = docs.headline_quotes,
        code_example     = docs.code_example,
        prerequisites    = docs.prerequisites,
        # github_researcher owns these
        repo_meta        = gh.repo_meta,
        readme_excerpt   = gh.readme_excerpt,
        file_list        = gh.file_list,
        # context_researcher owns these
        reactions        = context.reactions,
        related_releases = context.related_releases,
    )
    ctx.state["research"] = merged
    return Event(output={"sections_filled": [
        k for k, v in merged.model_dump().items() if v not in (None, [], "")
    ]})
```

Replace with:

```python
def _gather_research_impl(node_input, ctx: Context) -> Event:
    """§6.4.4 — counter-gated join: parse + merge docs/github/context
    dossiers into `research` once all 3 researchers have triggered.

    See docs/superpowers/specs/2026-05-01-fan-in-join-design.md for why
    this is gated (3 unconditional incoming edges → ADK re-triggers per
    predecessor → without the gate the entire writer chain cascades 3x).
    """
    n = ctx.state.get("gather_research_call_count", 0) + 1
    ctx.state["gather_research_call_count"] = n
    if n < 3:
        return Event()  # WAITING — predecessors can re-trigger.

    docs    = _parse_dossier(ctx.state.get("docs_research"),    "docs")
    gh      = _parse_dossier(ctx.state.get("github_research"),  "github")
    context = _parse_dossier(ctx.state.get("context_research"), "context")

    merged = ResearchDossier(
        # docs_researcher owns these
        summary          = docs.summary or context.summary or gh.summary,
        headline_quotes  = docs.headline_quotes,
        code_example     = docs.code_example,
        prerequisites    = docs.prerequisites,
        # github_researcher owns these
        repo_meta        = gh.repo_meta,
        readme_excerpt   = gh.readme_excerpt,
        file_list        = gh.file_list,
        # context_researcher owns these
        reactions        = context.reactions,
        related_releases = context.related_releases,
    )
    ctx.state["research"] = merged
    return Event(output={"sections_filled": [
        k for k, v in merged.model_dump().items() if v not in (None, [], "")
    ]})


gather_research = JoinFunctionNode(
    func=_gather_research_impl,
    name="gather_research",
)
```

Also add this import near the top of `nodes/aggregation.py` (after the existing `from google.adk import Context, Event` line):

```python
from nodes._join_node import JoinFunctionNode
```

- [ ] **Step 4: Run the new unit tests to verify they pass**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run pytest tests/test_aggregation.py -v`

Expected: `3 passed`.

- [ ] **Step 5: Run full suite to confirm no regression**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run pytest -q 2>&1 | tail -3`

Expected: `165 passed` (162 prior + 3 new).

- [ ] **Step 6: Verify `agent.py` still imports `gather_research` correctly**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run python -c "from agent import root_agent; nodes = [n.name for n in root_agent.graph.nodes]; print('gather_research' in nodes); print(type([n for n in root_agent.graph.nodes if n.name == 'gather_research'][0]).__name__)"`

Expected output:
```
True
JoinFunctionNode
```

This proves `gather_research` is now a `JoinFunctionNode` instance in the live graph.

- [ ] **Step 7: Commit**

```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
git add nodes/aggregation.py tests/test_aggregation.py && \
git commit -m "$(cat <<'EOF'
fix: gather_research as counter-gated JoinFunctionNode

Splits gather_research into _gather_research_impl (counter-gated function)
and a JoinFunctionNode instance. The counter (gather_research_call_count
in PipelineState) increments on each predecessor trigger; the join
proceeds only when the count reaches 3 (one per researcher).

Without this fix, each researcher's completion independently triggered
the entire writer chain (architect → drafter → critic → image_assets →
editor_request) → 3 duplicate Telegram editor messages per cycle.

See docs/superpowers/specs/2026-05-01-fan-in-join-design.md for the
full diagnosis with empirical evidence from session storage.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: Commit succeeds.

---

## Task 4: Add graph-shape regression test

**Files:**
- Create: `tests/test_graph_shape.py`

- [ ] **Step 1: Write the test**

Create `tests/test_graph_shape.py` with this exact content:

```python
"""Regression guard — fail the build if the workflow graph contains an
implicit fan-in (a node with multiple unconditional incoming edges that
isn't a JoinFunctionNode).

See docs/superpowers/specs/2026-05-01-fan-in-join-design.md for why this
matters: a plain FunctionNode with multiple unconditional incoming edges
re-fires its entire downstream chain once per predecessor, producing
duplicate side-effects (e.g., 3 editor Telegram messages per cycle)."""

from collections import defaultdict

from agent import root_agent
from nodes._join_node import JoinFunctionNode


def test_no_implicit_fan_in_in_root_agent():
    """Every node in root_agent.graph with > 1 unconditional incoming edge
    must be a JoinFunctionNode (which has wait_for_output=True)."""
    assert root_agent.graph is not None, "root_agent.graph not built"

    unconditional_in_count: dict[str, int] = defaultdict(int)
    for edge in root_agent.graph.edges:
        if edge.route is None:
            unconditional_in_count[edge.to_node.name] += 1

    nodes_by_name = {n.name: n for n in root_agent.graph.nodes}

    offenders = []
    for name, count in unconditional_in_count.items():
        if count <= 1:
            continue
        node = nodes_by_name[name]
        if not isinstance(node, JoinFunctionNode):
            offenders.append(
                f"{name!r}: {count} unconditional incoming edges, but is "
                f"{type(node).__name__} (must be JoinFunctionNode)"
            )

    assert not offenders, (
        "Implicit fan-in detected — these nodes have multiple unconditional "
        "incoming edges but are not JoinFunctionNode instances. They will "
        "re-fire downstream once per predecessor. Either reduce the incoming "
        "edges to 1 or refactor as a JoinFunctionNode. See "
        "docs/superpowers/specs/2026-05-01-fan-in-join-design.md.\n  - "
        + "\n  - ".join(offenders)
    )
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run pytest tests/test_graph_shape.py -v`

Expected: `1 passed`. (`gather_research` was the only fan-in offender, and it's now a `JoinFunctionNode` after Task 3.)

- [ ] **Step 3: Run full suite**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run pytest -q 2>&1 | tail -3`

Expected: `166 passed` (165 prior + 1 new).

- [ ] **Step 4: Commit**

```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
git add tests/test_graph_shape.py && \
git commit -m "$(cat <<'EOF'
test: graph-shape regression guard for implicit fan-in

Walks root_agent.graph.edges and asserts every node with > 1 unconditional
incoming edge is a JoinFunctionNode. Prevents future regressions where a
plain function with fan-in re-fires the entire downstream chain per
predecessor (the bug fixed in this same plan).

See docs/superpowers/specs/2026-05-01-fan-in-join-design.md.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Expected: Commit succeeds.

---

## Task 5: Deploy the engine update

**Files:** none (deploy.py invokes Vertex SDK)

- [ ] **Step 1: Verify .env has GOOGLE_CLOUD_PROJECT**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && grep -E "^GOOGLE_CLOUD_PROJECT=" .env`

Expected: `GOOGLE_CLOUD_PROJECT=gen-lang-client-0366435980`

- [ ] **Step 2: Deploy**

Run:
```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
set -a && source .env && set +a && \
uv run python deploy.py 2>&1 | tail -10
```

Expected output ends with:
```
Wrote deploy/.deployed_resource_id

Resource: projects/988979702911/locations/us-west1/reasoningEngines/2525375898861961216
```

(Takes ~3-5 minutes for `engine.update()` to complete server-side.)

---

## Task 6: Smoke trigger — fresh cycle, pause at topic_gate

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
    user_id='post-join-fix-smoke',
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
events=12  (or similar small number, ≤ 14)
pause=True
```

If `pause=False`: Scout parsed 0 candidates (intermittent Scout issue). Retry with `user_id='post-join-fix-smoke-2'`.

---

## Task 7: Operator approves topic_gate, observes single editor message

**Files:** none

- [ ] **Step 1: Operator taps Approve on the topic_gate Telegram message**

Tell the operator: "Tap Approve on the newest topic_gate message in your Telegram chat (it will reference the title that Scout selected). Wait 5-7 minutes for the editor review .md attachment to arrive."

- [ ] **Step 2: Acceptance #1 — verify exactly ONE editor message arrives**

Ask the operator: "How many editor review messages arrived in your chat since the topic_gate Approve?"

**Acceptance criterion:** Exactly **1** message.

- If 2 or 3: the fix didn't work. Run Step 3 to diagnose, then jump to Task 10 (rollback).
- If 0 after 8 minutes: engine error or scout/researcher hang. Run Step 3 to inspect.
- If 1: proceed to Step 3 (state inspection for #2 and #3).

- [ ] **Step 3: Acceptance #2 + #3 — inspect session state and event counts**

Run:
```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
uv run python -c "
import vertexai
from vertexai import agent_engines
vertexai.init(project='gen-lang-client-0366435980', location='us-west1')
engine = agent_engines.get(resource_name='projects/988979702911/locations/us-west1/reasoningEngines/2525375898861961216')
sessions = engine.list_sessions(user_id='post-join-fix-smoke').get('sessions', [])
s = sessions[0]
full = engine.get_session(user_id='post-join-fix-smoke', session_id=s['id'])
state = full.get('state', {})
events = full.get('events', [])

# Count distinct @N instances of gather_research and editor_request.
def instance_max(node_name):
    n = 0
    for ev in events:
        path = (ev.get('nodeInfo') or {}).get('path','')
        leaf = path.split('/')[-1] if '/' in path else ''
        if leaf.startswith(node_name + '@'):
            try:
                n = max(n, int(leaf.rsplit('@', 1)[1]))
            except ValueError:
                pass
    return n

print(f'gather_research instances:        {instance_max(\"gather_research\")}')
print(f'gather_research_call_count state: {state.get(\"gather_research_call_count\")}')
print(f'editor_request instances:         {instance_max(\"editor_request\")}')
print(f'writer_iterations:                {state.get(\"writer_iterations\")}')
print(f'critic_verdict:                   {state.get(\"critic_verdict\")}')
print(f'image_assets count:               {len(state.get(\"image_assets\") or [])}')
"
```

**Acceptance criteria:**
- `gather_research instances: 1` (was 3 in both pre-fix runs)
- `gather_research_call_count state: 3` (proves all 3 triggers landed but only one yielded output)
- `editor_request instances: 1` (was 3 in both pre-fix runs)
- `writer_iterations: ≤ 3`
- `image_assets count: ≥ 1` (image generation succeeded)

If any acceptance fails: jump to Task 10 (rollback).

---

## Task 8: Operator approves editor, observes Published confirmation

**Files:** none

- [ ] **Step 1: Operator taps Approve on the editor `.md` Telegram message**

Tell the operator: "Tap Approve on the editor review message. Wait 30-60s for the final ✅ Published confirmation."

- [ ] **Step 2: Verify exactly ONE Published confirmation**

Ask the operator: "Did you receive the ✅ Published message? How many?"

**Acceptance criterion:** Exactly **1** `✅ Published` message.

If 0 or > 1: jump to Task 10 (rollback).

- [ ] **Step 3: Acceptance #4 — verify cycle reached published state**

Run:
```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
uv run python -c "
import vertexai
from vertexai import agent_engines
vertexai.init(project='gen-lang-client-0366435980', location='us-west1')
engine = agent_engines.get(resource_name='projects/988979702911/locations/us-west1/reasoningEngines/2525375898861961216')
sessions = engine.list_sessions(user_id='post-join-fix-smoke').get('sessions', [])
s = sessions[0]
full = engine.get_session(user_id='post-join-fix-smoke', session_id=s['id'])
state = full.get('state', {})
ev = state.get('editor_verdict') or {}
ev_v = ev.get('verdict') if isinstance(ev, dict) else getattr(ev, 'verdict', None)
print(f'editor_iterations:      {state.get(\"editor_iterations\")}')
print(f'editor_verdict.verdict: {ev_v}')
print(f'cycle_outcome:          {state.get(\"cycle_outcome\")}')
print(f'asset_bundle_url:       {state.get(\"asset_bundle_url\")}')
"
```

**Acceptance criteria:**
- `editor_iterations: 1`
- `editor_verdict.verdict: approve`
- `cycle_outcome: published`
- `asset_bundle_url: gs://...` (a real URL)

If any acceptance fails: jump to Task 10 (rollback).

---

## Task 9: Tag the verified deploy

**Files:** none

- [ ] **Step 1: Tag the deploy**

Run:
```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
git tag -a v2-fan-in-join-fixed -m "Verified single editor message + Published cycle (post-join-fix-smoke) on $(date '+%Y-%m-%d')"
```

Expected: Tag created.

- [ ] **Step 2: Confirm clean working tree**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && git status`

Expected: `nothing to commit, working tree clean`.

---

## Task 10 (rollback — only if Task 7 or Task 8 acceptance fails)

**Files:**
- All commits from Tasks 1-4 reverted as a group.

- [ ] **Step 1: Identify the commit range to revert**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && git log --oneline -10`

Note the SHAs for the 4 fix commits (Tasks 1-4 — `feat: JoinFunctionNode...`, `feat: add gather_research_call_count...`, `fix: gather_research as counter-gated...`, `test: graph-shape regression guard...`).

- [ ] **Step 2: Revert the 4 commits in reverse order**

Run (replace `<sha>` with each SHA from Step 1, newest first):

```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
git revert --no-edit <sha-task-4> <sha-task-3> <sha-task-2> <sha-task-1>
```

Expected: 4 revert commits created.

- [ ] **Step 3: Run full suite to confirm baseline**

Run: `cd "/Users/rahulpatel/Documents/Content Gemini Agent" && uv run pytest -q 2>&1 | tail -3`

Expected: `161 passed` (back to pre-fix baseline).

- [ ] **Step 4: Redeploy baseline**

Run:
```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
set -a && source .env && set +a && \
uv run python deploy.py 2>&1 | tail -5
```

Expected: deploy succeeds; engine reverted to baseline.

- [ ] **Step 5: Capture the smoke session for post-mortem**

Run:
```bash
cd "/Users/rahulpatel/Documents/Content Gemini Agent" && \
uv run python -c "
import json
import vertexai
from vertexai import agent_engines
vertexai.init(project='gen-lang-client-0366435980', location='us-west1')
engine = agent_engines.get(resource_name='projects/988979702911/locations/us-west1/reasoningEngines/2525375898861961216')
sessions = engine.list_sessions(user_id='post-join-fix-smoke').get('sessions', [])
s = sessions[0]
full = engine.get_session(user_id='post-join-fix-smoke', session_id=s['id'])
print(json.dumps({'state': full.get('state', {}), 'event_count': len(full.get('events', []))}, indent=2, default=str))
" > /tmp/post-join-fix-smoke-postmortem.json
```

The dump is at `/tmp/post-join-fix-smoke-postmortem.json` for analysis. Surface the failure mode to the user with this evidence; do NOT attempt further fixes without a fresh diagnosis.
