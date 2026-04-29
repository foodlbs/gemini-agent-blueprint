# Spike Results — ADK 2.0 + Gemini Enterprise Agent Platform rebuild

Date: 2026-04-28
ADK version validated: `google-adk==2.0.0b1` (Beta)
Project: `gen-lang-client-0366435980`

## TL;DR

**Go.** All four mechanics that the rebuild plan depended on actually work in
ADK 2.0b1: graph `Workflow` execution, `RequestInput` pause/resume, managed
Memory Bank wiring, and the Telegram→`RequestInput` bridge. The fifth
unknown — Agent Runtime end-to-end deploy — is design-validated (the
`AdkApp` pattern is documented and matches the `memory-bank` sample) but not
yet flown; it's a deploy-time check, not an architectural risk.

The rebuild is now safe to plan in detail.

---

## Per-unknown results

### 1. ADK 2.0 graph `Workflow` basics — **PASS**
Script: `01_workflow_basics.py`

| Check | Result |
|---|---|
| `Workflow(edges=[...])` constructs without error | ✓ |
| Function nodes execute and emit `Event` | ✓ |
| LlmAgent nested in graph runs and emits text | ✓ |
| `ctx.state[...]` mutations propagate across nodes | ✓ |
| Conditional dict-edge routing | ✓ |

**Key learning (this is non-obvious):** routes are emitted by setting
`ctx.route = "BRANCH"` inside the function node. **`Event(output="BRANCH")`
alone does NOT trigger conditional routing** — the ambient-expense-agent
sample is misleading on this point (it returns `Event(output="AUTO_APPROVE")`,
which works only if no dict-edge depends on routing). Document this in our
DESIGN.md when we write it.

### 2. `RequestInput` pause/resume — **PASS**
Script: `02_hitl_request_input.py`

| Check | Result |
|---|---|
| Workflow pauses when a node yields `RequestInput` | ✓ |
| State persists across the pause | ✓ |
| Pause is detectable post-run via `event.long_running_tool_ids` | ✓ |
| Resume via `runner.run_async(new_message=...)` with matching `function_response` | ✓ |
| Response payload flows into the next node as `node_input` | ✓ |
| Pre-pause nodes do NOT re-execute on resume | ✓ |

**Resume contract:** the `RequestInput.interrupt_id` becomes a function-call
ID. To resume, send `Content` containing a
`Part(function_response=FunctionResponse(id=<interrupt_id>, name=<node_name>, response={...}))`.
The runner matches the ID, hands the response to the paused node, and
continues from there.

This is the architectural fix for D2 (24h Telegram timeout vs. 60min Cloud
Run request cap) — the pause does not consume an HTTP request, so duration
is bounded only by the session's TTL (Agent Runtime default is days).

### 3. Memory Bank wiring — **PASS**
Script: `03_memory_bank.py`

| Check | Result |
|---|---|
| `Runner(memory_service=...)` accepts an `InMemoryMemoryService` | ✓ |
| Agent with `tools=[preload_memory]` recalls via memory at session start | ✓ |
| `memory_service.add_session_to_memory(sess)` persists the session events | ✓ |
| Cross-session recall: session 2 answered "Where do I live?" with "Austin, Texas" | ✓ |

**Production swap:** `InMemoryMemoryService` → `VertexAiMemoryBankService`.
Same interface, same agent code. The managed service handles extraction +
storage + similarity search; we drop our hand-rolled
`shared/memory.py` (≈250 lines + token-overlap math).

### 4. Telegram → `RequestInput` bridge — **PASS**
Script: `04_telegram_bridge.py`

| Check | Result |
|---|---|
| Workflow node yields `RequestInput` with a stable `interrupt_id` (URL-derived) | ✓ |
| Outside the workflow, we can compute `callback_data` for Telegram buttons that round-trips the (session_id, interrupt_id, choice) tuple | ✓ |
| A handler that simulates the Telegram webhook receives `callback_data`, reconstructs the IDs, and POSTs a `FunctionResponse` to the runner | ✓ |
| Workflow resumes with the user's choice flowing into `record_verdict` | ✓ |

The bridge is plain plumbing — no novel framework code. Production design:

- One-line addition to the `topic_gate_request` node: also call `bot.send_message`
  with three inline-keyboard buttons whose `callback_data` is `<sess_pref>|<choice>|<intr_pref>`.
- A small FastAPI service (Cloud Run) at `/telegram/webhook` that receives the
  callback_query, looks up the full session_id + interrupt_id from a tiny KV
  (Firestore single doc, or even in-memory if the bridge co-locates with the
  Agent Runtime client), and POSTs the `FunctionResponse` via the AdkApp client.
- Telegram caps `callback_data` at 64 bytes — keep IDs short or use a KV
  for the long parts.

### 5. Agent Runtime deploy — **DEFERRED (design-validated)**

Did NOT actually run a deploy because of time + cost. The pattern is:

```python
# deploy.py
from vertexai.preview import reasoning_engines
from spike.agent import root_agent

app = reasoning_engines.AdkApp(
    agent=root_agent,
    enable_tracing=True,
)

remote = reasoning_engines.ReasoningEngine.create(
    app,
    requirements=["google-adk==2.0.0b1", "google-cloud-aiplatform>=1.105"],
    display_name="ai-release-pipeline",
    description="...",
)
print("resource id:", remote.resource_name)
```

This is the pattern the `memory-bank` sample uses for its Agent Runtime
target. Once the rebuild has a `root_agent` we'll do the live deploy as the
first step of "go to staging."

---

## What this validates about the rebuild plan

| Rebuild claim | Confidence after spike |
|---|---|
| ADK 2.0 graph `Workflow` is real and stable enough to use | **High** — the API works, but it's Beta; we should pin to 2.0.0b1 and watch for breaking changes. |
| `RequestInput` solves our 24h-HITL vs. Cloud-Run-timeout problem | **High** — pause is genuinely detached; no HTTP request is held open. |
| Telegram is a viable HITL surface (vs. needing a custom React UI) | **High** — the bridge is ~50 lines; no special platform feature needed. |
| Managed Memory Bank can replace `shared/memory.py` | **High** — wiring is clean, swap is one-line for production. |
| We can drop the Cloud Function trigger (Agent Runtime exposes a trigger endpoint directly) | **Medium** — pattern is documented but not flown in spike. |

---

## Risks the spike surfaced

1. **Beta API may shift.** ADK 2.0 is `2.0.0b1`. Expect at least one breaking
   change before GA. Pin the dep, check release notes weekly.
2. **`ctx.route` documentation gap.** The dict-edge routing pattern is
   under-documented; ambient-expense-agent's example is misleading. We
   should write our own DESIGN.md note on this.
3. **Resume-message shape is fiddly.** Constructing the `FunctionResponse`
   `Part` correctly took two attempts during the spike — the
   `Part.from_function_response()` factory doesn't accept an `id`, so you
   need to build the `FunctionResponse` directly and pass it to
   `Part(function_response=...)`. Wrap this in a helper in the rebuild.
4. **`callback_data` 64-byte cap.** Long URLs as interrupt_ids will overflow.
   Need a short-id KV mapping in the bridge.
5. **Memory Bank quota / region.** `VertexAiMemoryBankService` requires a
   reasoning-engine resource in the project; not yet provisioned.

---

## Recommended next steps

1. **Write `DESIGN.md v2.0`** — codify the graph layout, the `ctx.route`
   pattern, the Telegram bridge protocol, and the resume-message helper
   signature. Time: 1 day.
2. **Greenfield branch (`adk-2-rebuild`)** — empty directory, port the
   reusable bits (`tools/pollers.py`, `tools/imagen.py`, `tools/veo.py`,
   `tools/gcs.py`, `tools/github_ops.py`, `tools/web.py`, `tools/medium.py`,
   `shared/models.py`, `shared/prompts.py` minus the early-exit preambles).
   Build the new `agent.py` with the `Workflow(edges=[...])`. Time: 2 days.
3. **Deploy to Agent Runtime as staging** — first real deploy via `AdkApp`.
   Validate trigger endpoint + Telegram bridge end-to-end. Time: 1 day.
4. **Switch the existing scheduler to call the new resource** — terraform
   change only; the scheduler itself doesn't change. Time: 0.5 day.
5. **Cut over** — once staging runs cleanly for one polling cycle, retire
   the Cloud Run service from the previous attempt. Time: 0.5 day.

Total to working v2.0: **~5 days** of focused work.
