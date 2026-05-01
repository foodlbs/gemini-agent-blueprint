# Fan-In Join Fix: `gather_research` as `JoinFunctionNode`

**Date:** 2026-05-01
**Status:** Approved (after brainstorming Q1-Q3 + 2 implementation approaches)

## Problem

The operator receives **3 duplicate editor review messages** per polling
cycle in Telegram. After tapping Approve on one, in the broken state the
cycle stalls (`record_editor_verdict` never fires, `editor_verdict` stays
`None`, `cycle_outcome` stays `None`). In the previously-working state
(post-fix10-smoke and earlier), the cycle still published — but the
3 duplicate messages were always there as background noise; the user just
didn't notice because exactly one of them got resolved by the FR and the
cycle advanced anyway.

Empirical evidence from live session storage:

| user_id | `gather_research` runs | `editor_request` runs | `record_editor_verdict` runs | Outcome |
|---|---|---|---|---|
| post-fix10-smoke (worked) | **3x** | **3x** | 1x | published |
| post-crm-fix-smoke (broke) | **3x** | **3x** | **0x** | stuck |

Both runs have the same fan-in problem. The post-md-inject regression
(critic_split's strict marker check) made the 3 cascades hit forced-ACCEPT
and produce more state churn (writer_iterations=5 instead of 2), which is
how the FR ended up unmatched in the broken case.

## Root cause

`gather_research` is declared as a plain Python function:

```python
# nodes/aggregation.py
def gather_research(node_input, ctx: Context) -> Event:
    ...
    return Event(output={"sections_filled": [...]})
```

When ADK's graph builder encounters a plain callable (per
`_workflow_graph_utils.py:118-126`), it auto-wraps it as a `FunctionNode`
with `wait_for_output=False` (the default from `_base_node.py:65`). With
this default:

- Each predecessor's completion independently triggers the function.
- The function ALWAYS returns output (an `Event(output=...)`).
- ADK sees output → marks the node COMPLETED → triggers downstream.
- This happens 3 times (once per researcher) — `gather_research@1`,
  `gather_research@2`, `gather_research@3` — each independently
  cascading through the entire writer + asset chain to `editor_request`.

ADK's intended pattern for join nodes is the inverse — `wait_for_output=True`.
Per `_base_node.py:65-74`:

> If True, node only transitions to COMPLETED upon yielding output or
> route. Without output/route, the node enters WAITING state and downstream
> nodes are not triggered, allowing predecessors to re-trigger it.
> **This is useful for nodes like `JoinNode` that run multiple times before
> producing a final output.**

The function decides when "all inputs ready" by returning either `Event()`
(no output → stays WAITING) or `Event(output=...)` (proceeds).

## Audit findings

Every function node and LlmAgent in `agent.py`'s `edges` list, with
incoming-edge count broken into unconditional vs conditional. True fan-in =
≥ 2 unconditional incoming edges from distinct sources.

| Node | Incoming | True fan-in? |
|---|---|---|
| `scout_split` | 1 (scout) | no |
| `route_after_triage` | 1 (triage) | no |
| `record_triage_skip` | 1 conditional (SKIP) | no — terminal |
| `topic_gate_request` | 1 conditional (CONTINUE) | no |
| `record_topic_verdict` | 1 (topic_gate_request) | no |
| `route_topic_verdict` | 1 (record_topic_verdict) | no |
| `record_human_topic_skip` | 1 conditional (skip) | no — terminal |
| `record_topic_timeout` | 1 conditional (timeout) | no — terminal |
| **`gather_research`** | **3 unconditional** (docs/github/context) | **YES — bug** |
| `architect_split` | 1 (architect_llm) | no |
| `critic_split` | 1 (critic_llm) | no |
| `route_critic_verdict` | 1 (critic_split) | no |
| `image_asset_node` | 1 conditional (ACCEPT) | no |
| `video_asset_or_skip` | 1 (image_asset_node) | no |
| `gather_assets` | 1 (video_asset_or_skip) | no — name misleading; only 1 incoming |
| `route_needs_repo` | 1 (gather_assets) | no |
| `editor_request` | 3 conditional (WITHOUT_REPO + repo_builder + revision_writer loop) — mutually exclusive per traversal | no — convergence, not fan-in |
| `record_editor_verdict` | 1 (editor_request) | no |
| `route_editor_verdict` | 1 (record_editor_verdict) | no |
| `record_editor_rejection` | 1 conditional | no — terminal |
| `record_editor_timeout` | 1 conditional | no — terminal |
| `publisher` | 1 conditional (approve) | no — terminal |

LlmAgents inspected too: only `drafter` has > 1 incoming (architect_split
unconditional + route_critic_verdict REVISE conditional loopback). The
loopback is the intended write-rewrite loop (creates `@N` instances per
iteration), not a fan-in problem.

**Conclusion: `gather_research` is the only true fan-in. Single fix needed.**

## Design

### `nodes/_join_node.py` (new)

Reusable primitive that names what we're doing and centralizes the
`wait_for_output=True` setting:

```python
from google.adk.workflow import FunctionNode

class JoinFunctionNode(FunctionNode):
    """FunctionNode preconfigured as a graph join: stays WAITING until its
    function explicitly yields output. Use for nodes with multiple
    unconditional incoming edges. See ADK _base_node.py:65-74."""
    wait_for_output: bool = True
```

Pydantic subclass — no extra constructor wiring needed.

### `nodes/aggregation.py` — refactor `gather_research`

Split into impl function + node instance, with a counter check at the top:

```python
from google.adk import Context, Event
from nodes._join_node import JoinFunctionNode

# (existing _parse_dossier helper unchanged)

def _gather_research_impl(node_input, ctx: Context) -> Event:
    """§6.4.4 — join over (docs|github|context)_researcher.

    Counter-gated: returns no output until all 3 researchers have triggered.
    See docs/superpowers/specs/2026-05-01-fan-in-join-design.md."""
    n = ctx.state.get("gather_research_call_count", 0) + 1
    ctx.state["gather_research_call_count"] = n
    if n < 3:
        return Event()  # WAITING — predecessors can re-trigger

    # All 3 in. Merge and yield output.
    docs    = _parse_dossier(ctx.state.get("docs_research"),    "docs")
    gh      = _parse_dossier(ctx.state.get("github_research"),  "github")
    context = _parse_dossier(ctx.state.get("context_research"), "context")
    merged = ResearchDossier(
        summary          = docs.summary or context.summary or gh.summary,
        headline_quotes  = docs.headline_quotes,
        code_example     = docs.code_example,
        prerequisites    = docs.prerequisites,
        repo_meta        = gh.repo_meta,
        readme_excerpt   = gh.readme_excerpt,
        file_list        = gh.file_list,
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

`gather_assets` is unchanged (single incoming edge, audit confirmed).

### `shared/models.py` — add to `PipelineState`

```python
gather_research_call_count: int = 0
```

Type and default match the existing `chosen_release_write_count` pattern
exactly. `int = 0` (not `Optional[int] = None`) so `state.get(key, 0) + 1`
always works without None-handling. Avoid leading underscore (Pydantic
treats `_field` as PrivateAttr, which would break the state-field
declaration).

### `agent.py` — zero changes

Imports `gather_research` from `nodes.aggregation` exactly as before.
The wiring site is untouched.

## Test plan

### Pytest (must pass before deploy)

| File | Tests |
|---|---|
| `tests/test_join_node.py` (new) | `test_join_function_node_defaults_wait_for_output_true` — asserts `JoinFunctionNode(func=lambda *a, **k: None, name="x").wait_for_output is True` |
| `tests/test_aggregation.py` (new or extended) | `test_gather_research_returns_no_output_on_first_two_calls` — drives `_gather_research_impl` with stub Context, asserts return is `Event()` (no output) on calls 1 and 2; `test_gather_research_yields_merged_dossier_on_third_call` — call 3 returns `Event(output=...)` and writes `state["research"]`; `test_gather_research_counter_increments_in_state` — counter goes 1, 2, 3 |
| `tests/test_graph_shape.py` (new) | `test_no_implicit_fan_in_in_root_agent` — walks `root_agent.graph.edges`, counts unconditional incoming edges per node, asserts any node with > 1 is a `JoinFunctionNode` (or `LoopAgent` if any are added later) |

The graph-shape test guards against future regressions where someone wires
a fan-in without using `JoinFunctionNode`.

### Smoke acceptance gate (must pass before tagging the verified deploy)

Programmatic verification after deploy:

1. `engine.stream_query(user_id='post-join-fix-smoke', message='Run a polling cycle.')`
2. Wait for `topic_gate_request` pause.
3. Operator taps **Approve** on the topic_gate Telegram message.
4. Wait 5-7 minutes for editor review attachment.
5. **Acceptance #1**: count `editor_request` LRT yields in session events.
   Must be exactly **1** (was 3 in both pre-fix runs).
6. **Acceptance #2**: count distinct `gather_research` `@N` instances.
   Must be exactly **1** (was 3).
7. **Acceptance #3**: `state["writer_iterations"] ≤ 3`.
8. Operator taps **Approve** on the editor message.
9. Wait ~60s for `Published` confirmation.
10. **Acceptance #4**: `state["cycle_outcome"] == "published"`,
    `editor_iterations == 1`,
    `editor_verdict.verdict == "approve"`,
    `asset_bundle_url` is `gs://...`.

## Risks + rollback

| Risk | Severity | Mitigation |
|---|---|---|
| Researcher fails to write its `output_key` | Low | Counter is the gate, not state-key presence. Each trigger increments. At 3, the join proceeds; merged dossier handles missing keys via `_empty_dossier()`. |
| One researcher hangs (LLM stuck) | Low | `gather_research` stays WAITING. Sweeper picks up the session at 24h with `decision='timeout'`. Same behavior as today. |
| Counter not reset across cycles | None | Each cycle = new session = fresh state. Within a session, gather_research only fires in the research stage once. |
| State-field name collision | None — verified | No existing `gather_research_call_count` field in `PipelineState`. |
| Graph-shape test too strict | Low | Test exempts `JoinFunctionNode` (and `LoopAgent` if added later). Future legitimate fan-ins use the right primitive. |

**Rollback** (if smoke acceptance fails):

1. `git revert <fix-commit>` — single commit, clean.
2. `uv run pytest -q` — sanity.
3. `uv run python deploy.py` — redeploys baseline (today's reverted state). ~3 min.

Total rollback time: ~5 minutes. Worst case: back to "duplicate Telegram
messages but cycle progresses" — the baseline before this work started.

## Out of scope (Phase 2 — separate spec)

- `LoopAgent(max_iterations=3)` wrapping the writer loop (replaces the
  manual `writer_iterations` counter + `route_critic_verdict`'s forced-ACCEPT).
- `EscalationChecker(BaseAgent)` pattern for the sticky-key first-write-wins
  logic in `tools/state_helpers.write_state_json`.
- Restructuring the asset stage as a clean `image_asset → video_asset →
  gather_assets` (this is already the wiring; the prior over-firing was a
  downstream symptom of `gather_research` and goes away with this fix).

These are larger refactors that should not block restoring single-message
editor reviews.

## Risk assessment

**Low.** Three new files (one ~5-line subclass, one test for it, one graph
regression test), one logic change in an existing file, one new state
field. Easy to revert. Direct fix for the diagnosed root cause with strong
empirical evidence (live session events + ADK source citations).
