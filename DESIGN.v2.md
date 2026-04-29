# DESIGN.md v2.0 — AI Release → Article Pipeline (ADK 2.0 + Agent Runtime)

Status: **Draft / Outline** — sections marked `[TBD]` will be filled in
subsequent passes. Gate the rebuild on the operator signing off this
document.

Authoring rules for this document:
- Every claim must be implementable. If it depends on an unknown, mark
  it `[TBD]` and add to §15.
- Every node, tool, fact type, and env var named here is a contract with
  the code. Renaming requires a doc edit AND a code edit AND a test edit.
- **v1 is dead on arrival.** It deployed to Cloud Run but never produced a
  finished article (broken pollers, video_asset early-exit ignored, Veo
  model 404, Cloud Run 60-min cap fundamentally incompatible with 24h
  Telegram approvals). v2 replaces v1 wholesale. The only artifacts
  carried forward are the items listed in §14.
- **Region:** all v2 resources go in **`us-west1`** to match the existing
  Agent Runtime deployments in the project console.

---

## Table of contents

| § | Section | Status |
|---|---|---|
| 1 | What changes from v1.2 — the TL;DR delta table | **[DRAFTED]** |
| 2 | Goals & non-goals | **[DRAFTED]** |
| 3 | Architecture overview — diagram + deployment shape | **[DRAFTED]** |
| 4 | State schema — Pydantic models | **[DRAFTED]** |
| 5 | The Workflow graph — nodes, edges, routing | **[DRAFTED]** |
| 6 | Per-node specs | [chunk 4a/b/c] |
| 6.1 | Scout (LlmAgent + 7 pollers) | **[DRAFTED — chunk 4a]** |
| 6.2 | Triage + `route_after_triage` + `record_triage_skip` | **[DRAFTED — chunk 4a]** |
| 6.3 | Topic Gate (function + `RequestInput` + Telegram post) — HITL #1 | **[DRAFTED — chunk 4a]** |
| 6.4 | Researcher pool (parallel: docs, github, context) | **[DRAFTED — chunk 4b]** |
| 6.5 | Architect (LlmAgent → JSON blob → fan-out to state) | **[DRAFTED — chunk 4b]** |
| 6.6 | Writer loop (drafter ↔ critic, max 3 iterations) | **[DRAFTED — chunk 4b]** |
| 6.7 | Asset agent (parallel: image + video) | **[DRAFTED — chunk 4c]** |
| 6.8 | Repo router → Repo builder (conditional on `needs_repo`) | **[DRAFTED — chunk 4c]** |
| 6.9 | Editor (function + `RequestInput` + Telegram post) — HITL #2 | **[DRAFTED — chunk 4c]** |
| 6.10 | Revision writer (loop back to Editor) | **[DRAFTED — chunk 4c]** |
| 6.11 | Publisher / finalize node | **[DRAFTED — chunk 4c]** |
| 7 | Tools | **[DRAFTED — chunk 5]** |
| 7.1 | Pollers (port v1 + bug fixes) | **[DRAFTED — chunk 5]** |
| 7.2 | Memory Bank (managed `VertexAiMemoryBankService`) | **[DRAFTED — chunk 5]** |
| 7.3 | Telegram bot (post + bridge) | **[DRAFTED — chunk 5]** |
| 7.4 | Web fetch | **[DRAFTED — chunk 5]** |
| 7.5 | GitHub ops | **[DRAFTED — chunk 5]** |
| 7.6 | Imagen (image gen) | **[DRAFTED — chunk 5]** |
| 7.7 | Veo + video processing | **[DRAFTED — chunk 5]** |
| 7.8 | GCS upload | **[DRAFTED — chunk 5]** |
| 7.9 | Medium formatter | **[DRAFTED — chunk 5]** |
| 8 | HITL contract | **[DRAFTED — chunk 6]** |
| 8.1 | `RequestInput` shape — `interrupt_id`, `payload`, `message`, `response_schema` | **[DRAFTED — chunk 6]** |
| 8.2 | Telegram callback_data encoding (64-byte cap) | **[DRAFTED — chunk 6]** |
| 8.3 | Resume protocol (FunctionResponse `Part`) | **[DRAFTED — chunk 6]** |
| 8.4 | Timeout & escalation | **[DRAFTED — chunk 6]** |
| 9 | Memory Bank schema | **[DRAFTED — chunk 6]** |
| 9.1 | Fact types: `covered`, `human-rejected` | **[DRAFTED — chunk 6]** |
| 9.2 | Scope: `ai_release_pipeline` | **[DRAFTED — chunk 6]** |
| 9.3 | Triage query semantics + similarity threshold | **[DRAFTED — chunk 6]** |
| 9.4 | When Editor + Topic Gate write | **[DRAFTED — chunk 6]** |
| 10 | Deployment | **[DRAFTED — chunk 7]** |
| 10.1 | `AdkApp` + `ReasoningEngine` pattern | **[DRAFTED — chunk 7]** |
| 10.2 | Dependency pin (`google-adk==2.0.0bX`) | **[DRAFTED — chunk 7]** |
| 10.3 | Service account + IAM | **[DRAFTED — chunk 7]** |
| 10.4 | Secret Manager refs | **[DRAFTED — chunk 7]** |
| 10.5 | Cloud Scheduler trigger (no Cloud Function needed) | **[DRAFTED — chunk 7]** |
| 10.6 | Telegram webhook (separate Cloud Run) | **[DRAFTED — chunk 7]** |
| 11 | Observability | **[DRAFTED — chunk 7]** |
| 11.1 | Cloud Trace (auto) | **[DRAFTED — chunk 7]** |
| 11.2 | Cloud Logging filters | **[DRAFTED — chunk 7]** |
| 11.3 | GenAI Evaluation Service | **[DRAFTED — chunk 7]** |
| 12 | Failure modes & recovery | **[DRAFTED — chunk 8]** |
| 12.1 | LLM call fails | **[DRAFTED — chunk 8]** |
| 12.2 | Tool call fails | **[DRAFTED — chunk 8]** |
| 12.3 | Memory Bank unavailable | **[DRAFTED — chunk 8]** |
| 12.4 | Telegram down | **[DRAFTED — chunk 8]** |
| 12.5 | `RequestInput` timeout (24h+) | **[DRAFTED — chunk 8]** |
| 12.6 | Asset generation 404 / quota | **[DRAFTED — chunk 8]** |
| 13 | Eval strategy | **[DRAFTED — chunk 8]** |
| 13.1 | Unit tests (per tool) | **[DRAFTED — chunk 8]** |
| 13.2 | Workflow tests (mocked LLM, real graph) | **[DRAFTED — chunk 8]** |
| 13.3 | Live evals via GenAI Eval Service | **[DRAFTED — chunk 8]** |
| 14 | What survives v1 → v2 (one table, no rollout phases) | **[DRAFTED — chunk 8]** |
| 15 | Open questions / decisions needed | [TBD chunk 8] |

---

---

## §1 — What changes from v1.2 (TL;DR delta)

| Dimension | v1.2 (Cloud Run) | v2.0 (Agent Runtime) |
|---|---|---|
| ADK version | `1.31.1` (composition primitives) | `2.0.0bX` (graph `Workflow`) — Beta, pinned |
| Top-level orchestration | `SequentialAgent` of 8 stages, with nested `ParallelAgent` and `LoopAgent` containers | One `Workflow(edges=[...])` declaring the whole graph |
| Conditional branching | `LlmAgent` `transfer_to_agent` (e.g. `repo_router` LLM-deciding) | Function node sets `ctx.route = "BRANCH"`; dict-edge picks next node — code-deterministic |
| Early-exit guards | LLM prompt preamble (`If state['chosen_release'] is None, end your turn immediately`) — **the LLM ignored this for `video_asset_agent` in production (Bug B2)** | Function node guard before the LLM agent — physically impossible to bypass |
| State mutation contract | `output_key` writes one key; multi-key writes via JSON-blob + `after_agent_callback` parser (Architect: 8 keys, Editor: 4 keys) | Function nodes write directly to `ctx.state[...]`; LLM nodes still use `output_key` for single-key outputs |
| Deployment target | Cloud Run service, `us-east1` | Agent Runtime ReasoningEngine, `us-west1` |
| Runtime container | `Dockerfile` + Cloud Build (had to add `ffmpeg`, had to add missing `COPY` lines for `main.py`/`agents/`/`tools/`/`shared/`) | Source-based `AdkApp(...).deploy()` — no Dockerfile, no Cloud Build |
| Request lifecycle | Bound by HTTP request timeout (max 60min for Cloud Run) | Detached: pause via `RequestInput` does not hold an HTTP request open; bound only by session TTL (days) |
| Human-in-the-loop | Long-poll Telegram `getUpdates` with 24h timeout — **fundamentally incompatible with Cloud Run's 60min cap (Issue D2)** | `RequestInput` event pauses workflow; Telegram bridge resumes via `FunctionResponse` — pause cost is zero compute |
| Session storage | `InMemorySessionService` — state lost on Cloud Run cold start | Managed Sessions — durable across pause / restart / instance churn |
| Memory Bank | Hand-rolled `shared/memory.py` (~250 LoC, token-overlap similarity, in-process backend that didn't survive restarts) | Managed `VertexAiMemoryBankService` — auto-extraction, embedding-based recall, persistent |
| Trigger path | Cloud Scheduler → Pub/Sub → Cloud Function (Gen2) → Cloud Run | Cloud Scheduler → Agent Runtime trigger endpoint (no function, no Pub/Sub) — IF this works (§15 Q3); else keep the function but point it at the Agent Runtime |
| Auth (caller → service) | `--no-allow-unauthenticated` + OIDC ID token | Agent Identity (SPIFFE) — managed by Agent Runtime |
| Secrets | Created via `gcloud secrets create`, passed via `gcloud run deploy --set-secrets` (passthrough flag) | Referenced in `deploy.py` (`AdkApp` accepts secret bindings); same Secret Manager backing store |
| Telegram tooling | `tools/telegram_approval.py` — long-polls, blocks the calling turn for up to 24h | Two artifacts: (a) Python helper that posts the message + buttons (called inside the workflow's HITL function node); (b) FastAPI Cloud Run service that handles `/telegram/webhook` and resumes the paused session |
| Pollers | `arxiv`/`github`/`rss`/`hf_models` — three of four had a `datetime` vs `str` bug or stale kwarg in production (Bug B1, since fixed) | Carry over verbatim — already fixed and live-tested against 11/10 sources |
| Researcher pool | `ParallelAgent(name="researcher_pool", sub_agents=[docs, github, context])` | Same intent, expressed as 3 parallel branches in the graph; uses `ParallelAgent` inside a graph node OR plain `asyncio.gather` in a function node — pick one in §6.4 |
| Writer loop | `LoopAgent(name="writer_loop", max_iterations=3, sub_agents=[drafter, critic])` | Same iteration cap; expressed as a self-loop edge in the graph (`(critic, route_writer_verdict, {"REVISE": drafter, "ACCEPT": next_node})`) |
| Asset agent | `ParallelAgent(name="asset_agent", sub_agents=[image, video])` | Same — parallel branches in the graph; the broken video early-exit is replaced by a function-node guard upstream |
| Repo Builder | `LlmAgent(name="repo_router")` with sub-agent `repo_builder` and inline prompt in `main.py` | Function-node router (`route_needs_repo` → dict-edge), `repo_builder` is a plain LlmAgent — no nested router |
| Editor + Revision Writer | `LoopAgent(name="revision_loop", max_iterations=3, sub_agents=[editor, revision_writer])` | Editor is a HITL function node + LlmAgent for the verdict-formatting; loop edge: `(revision_writer, editor)` with route `revise` |
| Files in source tree | ~100 (pre-rebuild): 10 per-agent dirs + scaffold artifacts + Cloud Function + Dockerfile + scheduler.tf + ... | ~30 (target): one `agent.py`, `tools/`, `shared/`, `deploy.py`, `telegram_bridge/`, `tests/` |
| Tests | 197 unit + 4 skipped + 4 evalsets | Carry over the 100% of tests that test pure tool logic (~120 tests); rewrite all agent-wiring tests for the graph (~70 tests); reuse the evalset shape but run via GenAI Eval Service |
| Observability | Cloud Trace via `otel_to_cloud=True`; manual Cloud Logging; no eval automation | Cloud Trace (auto in Agent Runtime); Cloud Logging filters preserved; **GenAI Evaluation Service** for managed Auto SxS evals |
| Rejected v1 patterns kept out of v2 | — | (a) Inline LlmAgent prompts in `main.py` (e.g. v1 `repo_router`); (b) JSON-blob fan-out in `output_key` followed by callback parser (replace with function-node direct writes); (c) Custom local Memory Bank backend that pretends to be Vertex (replace with the actual managed service) |

**Three of these rows changed only because v2 fixes specific v1 production
bugs** — they are NOT preference changes:

- **Early-exit guards** are code, not prompts → kills the entire class of
  bugs B2 produced.
- **Pollers** stay verbatim → those bugs (B1) are already fixed in
  `tools/pollers.py` on the current working tree.
- **HTTP lifecycle** changes from "request held open" to "session
  detached" → kills D2 (24h Telegram vs 60min Cloud Run).

---

## §2 — Goals & non-goals

### Goals (each one is testable)

1. **Each polling cycle terminates in one of two states**, with a Memory
   Bank fact recording the outcome:
   - SKIPPED — `chosen_release=None`, `skip_reason` is a non-empty string,
     and a `human-rejected` fact is written when the skip was a Topic Gate
     human decision.
   - PUBLISHED — a Markdown article (Medium-formatted) and an asset bundle
     URL exist in `state`, the GitHub starter repo URL is present iff
     `needs_repo=True`, and a `covered` fact is written.
2. **Two human approval gates work without a 24h ceiling on Cloud
   Run / Agent Runtime side.** The pipeline must survive a 23h59m
   approval delay and resume cleanly when the human eventually replies.
3. **Hourly cron** via Cloud Scheduler. Manually-triggerable by Pub/Sub
   publish for ad-hoc runs.
4. **Idempotency on duplicate trigger.** If Cloud Scheduler fires a second
   trigger while the first cycle is still HITL-paused, the second trigger
   must not steal the in-flight session. Default: **drop** the second
   trigger and log a warning. (Open question §15 Q4 may revise this.)
5. **No silent failures.** Every tool that could return `[]` on error
   must log the cause; every node that could no-op must `escalate` so the
   workflow ends cleanly rather than continuing into garbage state.
6. **Memory Bank is the source of truth for "have we covered this?"**
   No local cache, no in-process dedup. Triage queries the managed
   service every cycle.
7. **Architectural decisions in v1 that produced production bugs are
   replaced by code-level enforcement, not by prompt revisions.** Listed
   per node in §6.
8. **Total source size budget: under 2000 lines of code excluding
   tests.** v1 was ~3000 LoC and we want the rebuild leaner.

### Non-goals (v2 scope — explicitly out)

1. **No frontend / dashboard.** Telegram is the only operator surface.
2. **Single-tenant.** One Telegram chat ID, one bot token, one GCP
   project. Multi-tenant is v3+.
3. **No real-time streaming to operator.** All operator interaction is
   message-driven (Telegram). The pipeline can take 5–30 minutes per
   cycle and that's fine.
4. **No publishing to Medium / Dev.to / X automatically.** The Editor's
   "approve" verdict produces the Markdown + assets in `state` and writes
   them to a GCS bucket; an out-of-band human (or a future v3 feature)
   pushes them to a publication. Reason: publication APIs change too
   often to bake into v2 scope.
5. **No multi-source per-article merging.** One release → one article.
   No "round-up" articles aggregating multiple releases.
6. **No cost optimization in v2.** Focus on correctness. Throttling,
   caching, and model-selection optimization are deferred. Veo will be
   gated by `needs_video` (defaults to `False`).
7. **No backward compatibility with v1.** v1 is dead. Old session IDs,
   old Memory Bank entries, old GCS objects can be deleted. The only v1
   state we explicitly preserve is the `human-rejected` fact set in
   Memory Bank — those represent operator decisions and we don't want
   to forget them.

---

## §3 — Architecture overview

### Deployment shape (3 long-lived resources + 4 supporting)

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Cloud Scheduler  (us-west1)                                             │
│   job: ai-release-pipeline-v2-hourly                                     │
│   schedule: 0 * * * *  (PAUSED at create — operator unpauses)            │
│                                                                          │
│   target: HTTP POST → Agent Runtime trigger endpoint                     │
│           (or Pub/Sub topic if the direct HTTP trigger is unavailable —  │
│            §15 Q3, decided in chunk 7)                                   │
└──────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼  POST {"trigger": "scheduler"}
┌──────────────────────────────────────────────────────────────────────────┐
│  Agent Runtime ReasoningEngine  (us-west1)                               │
│   resource: ai-release-pipeline-v2                                       │
│   identity: SPIFFE-formatted Agent Identity (managed)                    │
│                                                                          │
│   AdkApp(agent=root_agent, enable_tracing=True)                          │
│                                                                          │
│   root_agent = Workflow(name="ai_release_pipeline_v2", edges=[           │
│     ("START", scout, triage, route_chosen, {                             │
│         "SKIP":      record_skip,                                        │
│         "CONTINUE":  topic_gate_post,                                    │
│     }),                                                                  │
│     (topic_gate_post, topic_gate_wait, route_topic_verdict, {            │
│         "skip":     record_human_skip,                                   │
│         "approve":  research_fanout,                                     │
│     }),                                                                  │
│     (research_fanout, architect, drafter, critic, route_critic, {        │
│         "REVISE":  drafter,                                              │
│         "ACCEPT":  asset_fanout,                                         │
│     }),                                                                  │
│     (asset_fanout, route_needs_repo, {                                   │
│         "WITH_REPO":    repo_builder,                                    │
│         "WITHOUT_REPO": editor_post,                                     │
│     }),                                                                  │
│     (repo_builder, editor_post),                                         │
│     (editor_post, editor_wait, route_editor_verdict, {                   │
│         "approve":  publisher,                                           │
│         "revise":   revision_writer,                                     │
│         "reject":   record_rejection,                                    │
│     }),                                                                  │
│     (revision_writer, editor_post),  # loop back                         │
│   ])                                                                     │
│                                                                          │
│   uses (managed): Sessions, Memory Bank, Cloud Trace                     │
└──────────────────────────────────────────────────────────────────────────┘
        │                        │                        │
        │ memory ops              │ tool calls              │ HITL pause/resume
        ▼                        ▼                        │
┌────────────────────┐  ┌─────────────────────┐           │
│  Memory Bank       │  │ External services   │           │
│   (us-west1)       │  │  ArXiv, GitHub,     │           │
│   facts:           │  │  HuggingFace,       │           │
│    - covered       │  │  HN Algolia,        │           │
│    - human-        │  │  Anthropic /news,   │           │
│      rejected      │  │  8 RSS feeds,       │           │
└────────────────────┘  │  Vertex Imagen,     │           │
                        │  Vertex Veo,        │           │
                        │  GCS bucket,        │           │
                        │  GitHub API,        │           │
                        │  Telegram Bot API   │           │
                        └─────────────────────┘           │
                                                          │
                                                          ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  Telegram Bridge — Cloud Run service  (us-west1)                         │
│   service: ai-release-pipeline-v2-telegram                               │
│   identity: dedicated SA with `roles/aiplatform.user`                    │
│                                                                          │
│   FastAPI:                                                               │
│     POST /telegram/webhook                                               │
│       1. Verify Telegram secret token (via `--update-secrets`)           │
│       2. Parse callback_query → (session_prefix, choice, interrupt_pref) │
│       3. Look up full IDs in tiny Firestore doc (or in-memory KV         │
│          if single-instance Cloud Run is enough — chunk 7 decides)       │
│       4. POST FunctionResponse to AdkApp client → resume session         │
│                                                                          │
│   No long-running state; just a thin shim. Min instances: 0.             │
└──────────────────────────────────────────────────────────────────────────┘
```

### Three resources for the operator to remember

| Resource | What it does | Where to look when it breaks |
|---|---|---|
| `ReasoningEngine: ai-release-pipeline-v2` | The pipeline itself | GCP Console → Gemini Enterprise Agent Platform → Deployments |
| `CloudRun: ai-release-pipeline-v2-telegram` | Telegram → resume bridge | GCP Console → Cloud Run |
| `CloudScheduler: ai-release-pipeline-v2-hourly` | Cron trigger | GCP Console → Cloud Scheduler |

### Four supporting resources (provisioned via Terraform, never touched after creation)

| Resource | Purpose |
|---|---|
| GCS bucket `gen-lang-client-0366435980-airel-assets-v2` | Asset hosting (90-day TTL) — fresh bucket, drop v1's |
| Secret Manager `airel-v2-github-token` | GitHub PAT for repo creation |
| Secret Manager `airel-v2-telegram-bot-token` | Telegram bot token |
| Secret Manager `airel-v2-telegram-webhook-secret` | Random token Telegram echoes back so the bridge can verify the webhook |
| Memory Bank `airel-v2-memory` (instance, not just service) | The actual reasoning-engine-attached memory store; provisioned via `agents-cli infra single-project` or `gcloud ai memory-banks create` (decide in chunk 7) |

### Two principles the diagram enforces

1. **The Workflow graph is the single source of truth for control flow.**
   No agent decides which agent runs next. Either an edge says so (static)
   or a function node sets `ctx.route` (dynamic). LlmAgents do work; they
   do not orchestrate.
2. **The HITL bridge is the only thing outside the Agent Runtime that
   touches sessions.** Cloud Scheduler triggers START. Telegram bridge
   resumes paused sessions. Nothing else has session-level write
   permission. This minimizes the blast radius of bugs in the bridge.

---

## §4 — State schema

### Why a top-level `PipelineState` Pydantic model

ADK 2.0 `Workflow` accepts a `state_schema=` Pydantic class. When set,
the framework:
- validates every `ctx.state["foo"] = ...` write against the schema,
- type-checks the parameter binding when function nodes declare typed
  parameters that name state keys,
- raises `StateSchemaError` at workflow construction time if a function
  node references a state key that isn't in the schema.

v1 used a plain `dict` and discovered missing keys at runtime. v2 makes
`PipelineState` the single source of truth — every state key is declared
once, with a type, and the framework enforces it.

### `PipelineState` (the v2 contract)

```python
# shared/models.py

from datetime import datetime
from typing import Literal, Optional
from pydantic import BaseModel, Field


SourceType = Literal[
    "arxiv", "github", "huggingface",
    "anthropic", "google", "openai", "deepmind", "meta",
    "mistral", "nvidia", "microsoft", "bair",
    "huggingface_papers", "huggingface_blog", "hackernews",
    "other",
]
ArticleType = Literal["quickstart", "explainer", "comparison", "release_recap"]
ImageStyle = Literal["photoreal", "diagram", "illustration", "screenshot"]
AspectRatio = Literal["16:9", "4:3"]
CriticVerdict = Literal["accept", "revise"]
EditorDecision = Literal["approve", "reject", "revise", "timeout"]
TopicDecision = Literal["approve", "skip", "timeout"]


class Candidate(BaseModel):
    title: str
    url: str
    source: SourceType
    published_at: datetime
    raw_summary: str


class ChosenRelease(Candidate):
    score: int = Field(ge=0, le=100)
    rationale: str
    top_alternatives: list[Candidate] = Field(default_factory=list, max_length=2)


class TopicVerdict(BaseModel):
    verdict: TopicDecision
    at: datetime


class ResearchDossier(BaseModel):
    summary: str
    headline_quotes: list[str] = Field(default_factory=list, max_length=2)
    code_example: Optional[str] = None
    prerequisites: list[str] = Field(default_factory=list)
    repo_meta: Optional[dict] = None
    readme_excerpt: Optional[str] = None
    file_list: list[str] = Field(default_factory=list)
    reactions: list[str] = Field(default_factory=list)
    related_releases: list[str] = Field(default_factory=list)


class OutlineSection(BaseModel):
    heading: str
    intent: str
    research_items: list[str] = Field(default_factory=list)
    word_count: int


class Outline(BaseModel):
    sections: list[OutlineSection]
    working_title: str
    working_subtitle: str
    article_type: ArticleType


class ImageBrief(BaseModel):
    position: str  # "hero", "section_2", etc.
    description: str
    style: ImageStyle
    aspect_ratio: AspectRatio


class VideoBrief(BaseModel):
    description: str
    style: str
    duration_seconds: int = Field(ge=4, le=8)
    aspect_ratio: AspectRatio = "16:9"


class ImageAsset(BaseModel):
    position: str
    url: str  # GCS public URL
    alt_text: str
    aspect_ratio: AspectRatio


class VideoAsset(BaseModel):
    mp4_url: str
    gif_url: str
    poster_url: str
    duration_seconds: int


class Draft(BaseModel):
    markdown: str
    iteration: int = 0
    critic_feedback: Optional[str] = None
    critic_verdict: Optional[CriticVerdict] = None


class RevisionFeedback(BaseModel):
    feedback: str
    at: datetime


class EditorVerdict(BaseModel):
    verdict: EditorDecision
    feedback: Optional[str] = None
    at: datetime


class StarterRepo(BaseModel):
    url: str
    files_committed: list[str]
    sha: str


class PipelineState(BaseModel):
    """Top-level Workflow state schema — every key the graph touches.

    Validated by ADK at workflow construction time. Function nodes that
    declare typed parameters matching these names get auto-bound from
    state.
    """

    # --- Trigger / scheduling ---
    last_run_at: Optional[datetime] = None
    """Set by the trigger entry node from the Cloud Scheduler payload."""

    # --- Scout ---
    candidates: list[Candidate] = Field(default_factory=list)
    """All candidate releases collected by Scout this cycle."""

    # --- Triage ---
    chosen_release: Optional[ChosenRelease] = None
    """The one candidate Triage picked, OR None if Triage skipped."""
    skip_reason: Optional[str] = None
    """Set when chosen_release is None. Free-text explanation."""

    # --- Topic Gate (HITL #1) ---
    topic_verdict: Optional[TopicVerdict] = None
    """The human's response to the topic-approval Telegram post."""

    # --- Researcher pool ---
    docs_research: Optional[ResearchDossier] = None
    github_research: Optional[ResearchDossier] = None
    context_research: Optional[ResearchDossier] = None
    research: Optional[ResearchDossier] = None
    """Merged dossier produced by gather_research from the three above."""

    # --- Architect ---
    outline: Optional[Outline] = None
    image_briefs: list[ImageBrief] = Field(default_factory=list)
    video_brief: Optional[VideoBrief] = None
    needs_video: bool = False
    needs_repo: bool = False

    # --- Writer loop ---
    draft: Optional[Draft] = None
    """Current draft being iterated. Drafter writes; Critic annotates."""
    writer_iterations: int = 0
    """Hard cap counter — Critic forces ACCEPT once this hits 3."""

    # --- Asset agent ---
    image_assets: list[ImageAsset] = Field(default_factory=list)
    video_asset: Optional[VideoAsset] = None

    # --- Repo Builder (conditional) ---
    starter_repo: Optional[StarterRepo] = None

    # --- Editor (HITL #2) + Revision Writer loop ---
    editor_verdict: Optional[EditorVerdict] = None
    human_feedback: Optional[RevisionFeedback] = None
    """Set by record_editor_verdict on revise; consumed by revision_writer."""
    editor_iterations: int = 0
    """Hard cap counter — record_editor_verdict forces approve/reject after 3."""

    # --- Publisher ---
    final_markdown: Optional[str] = None
    """Medium-formatted final draft, written by publisher."""
    asset_bundle_url: Optional[str] = None
    """GCS URL of the bundled assets (markdown + images + video)."""
    memory_bank_recorded: bool = False
    """True after publisher writes the `covered` Memory Bank fact."""

    # --- Cycle outcome (mutually exclusive with the above) ---
    cycle_outcome: Optional[Literal[
        "skipped_by_triage",
        "skipped_by_human_topic",
        "topic_timeout",
        "rejected_by_editor",
        "editor_timeout",
        "published",
    ]] = None
    """Set by exactly one terminal node. Read by post-cycle reporting."""
```

### Field lifecycle table — who writes, who reads

| Field | Written by | Read by | Cleared on |
|---|---|---|---|
| `last_run_at` | Trigger entry | Scout, Triage | New cycle |
| `candidates` | `scout` (LlmAgent, `output_key="candidates"`) | Triage | New cycle |
| `chosen_release` | `triage` (via `write_state_json` tool) | Every node from Topic Gate onward | New cycle |
| `skip_reason` | `triage`, `record_triage_skip`, `record_topic_timeout` | Reporter (out-of-band) | New cycle |
| `topic_verdict` | `record_topic_verdict` | `route_topic_verdict` | New cycle |
| `docs_research` | `docs_researcher` | `gather_research` | New cycle |
| `github_research` | `github_researcher` | `gather_research` | New cycle |
| `context_research` | `context_researcher` | `gather_research` | New cycle |
| `research` | `gather_research` (function) | `architect` | New cycle |
| `outline`, `image_briefs`, `video_brief`, `needs_video`, `needs_repo` | `architect_split` (function: parses `_architect_raw` → 5 state writes, no JSON-blob+callback dance like v1) | Writer, asset, repo router | New cycle |
| `draft` | `drafter` (LlmAgent, `output_key="draft"`); `revision_writer` (rewrites) | `critic`, `editor`, `publisher` | New cycle |
| `writer_iterations` | `critic_split` (increment + verdict parse) | `route_critic_verdict` | New cycle |
| `image_assets` | `image_asset_agent` (one per `image_briefs` entry) | `editor`, `publisher` | New cycle |
| `video_asset` | `video_asset_agent` (only if `needs_video=True`) | `editor`, `publisher` | New cycle |
| `starter_repo` | `repo_builder` (only if `needs_repo=True`) | `editor`, `publisher` | New cycle |
| `editor_verdict` | `record_editor_verdict` | `route_editor_verdict` | New cycle |
| `human_feedback` | `record_editor_verdict` (on revise) | `revision_writer` | New cycle |
| `editor_iterations` | `record_editor_verdict` | `record_editor_verdict` (cap enforcement) | New cycle |
| `final_markdown` | `publisher` | (out-of-band consumer) | New cycle |
| `asset_bundle_url` | `publisher` | (out-of-band consumer) | New cycle |
| `memory_bank_recorded` | `publisher` (after Memory Bank write succeeds) | (out-of-band) | New cycle |
| `cycle_outcome` | exactly one terminal node | Reporter | New cycle |

### State invariants the framework MUST enforce

1. **Once `chosen_release` is non-None, downstream nodes assume the
   release is real.** No node from `topic_gate_request` onward needs to
   check `chosen_release is None` — the routing already routed past
   them. (This is the v1 bug B2 fix made structural.)
2. **Exactly one of `cycle_outcome` is set when the workflow ends.**
   Terminal nodes are responsible. If the workflow ends without
   `cycle_outcome` set, that's a programming error (test enforces).
3. **`topic_verdict` is set iff `record_topic_verdict` ran.** If
   Triage skipped, `topic_verdict` stays None.
4. **`writer_iterations` and `editor_iterations` are monotonic.** Only
   the verdict-recording nodes increment them.
5. **`draft.iteration` matches `writer_iterations - 1`** (the draft was
   produced before the critic incremented). Test enforces.

---

## §5 — The Workflow graph

### Canonical edge list (what we will literally write in `agent.py`)

```python
# agent.py

from google.adk import Workflow

from agents.scout import scout                       # LlmAgent
from agents.triage import triage                     # LlmAgent
from agents.researchers import (
    docs_researcher, github_researcher, context_researcher,
)                                                    # 3 LlmAgents
from agents.architect import architect_llm           # LlmAgent
from agents.writer import drafter, critic_llm        # 2 LlmAgents
from agents.assets import image_asset_agent          # 1 LlmAgent
from agents.repo_builder import repo_builder         # LlmAgent
from agents.revision_writer import revision_writer   # LlmAgent

from nodes.routing import (
    route_after_triage, route_topic_verdict,
    route_critic_verdict, route_needs_repo, route_editor_verdict,
)
from nodes.hitl import topic_gate_request, editor_request
from nodes.records import (
    record_topic_verdict, record_editor_verdict,
    record_triage_skip, record_human_topic_skip, record_topic_timeout,
    record_editor_rejection, record_editor_timeout,
)
from nodes.aggregation import gather_research, gather_assets
from nodes.architect_split import architect_split
from nodes.critic_split import critic_split
from nodes.video_asset import video_asset_or_skip    # function node, NOT an LlmAgent
from nodes.publisher import publisher
from shared.models import PipelineState


root_agent = Workflow(
    name="ai_release_pipeline_v2",
    state_schema=PipelineState,
    edges=[
        # --- 1. Scout → Triage ---------------------------------------------
        ("START", scout, triage, route_after_triage, {
            "SKIP":     record_triage_skip,
            "CONTINUE": topic_gate_request,
        }),

        # --- 2. Topic Gate (HITL #1) — fan-out to research on approve -----
        (topic_gate_request, record_topic_verdict, route_topic_verdict, {
            "approve":  (docs_researcher, github_researcher, context_researcher),
            "skip":     record_human_topic_skip,
            "timeout":  record_topic_timeout,
        }),

        # --- 3. Research join → Architect → Writer loop -------------------
        (docs_researcher,    gather_research),
        (github_researcher,  gather_research),
        (context_researcher, gather_research),
        (gather_research, architect_llm, architect_split, drafter,
                                       critic_llm, critic_split,
                                       route_critic_verdict, {
            "REVISE": drafter,
            "ACCEPT": (image_asset_agent, video_asset_or_skip),
        }),

        # --- 4. Asset join → repo router → editor -------------------------
        (image_asset_agent, gather_assets),
        (video_asset_or_skip, gather_assets),
        (gather_assets, route_needs_repo, {
            "WITH_REPO":    repo_builder,
            "WITHOUT_REPO": editor_request,
        }),
        (repo_builder, editor_request),

        # --- 5. Editor (HITL #2) — approve / revise loop / reject ---------
        (editor_request, record_editor_verdict, route_editor_verdict, {
            "approve":  publisher,
            "reject":   record_editor_rejection,
            "revise":   revision_writer,
            "timeout":  record_editor_timeout,
        }),
        (revision_writer, editor_request),  # loop back into HITL
    ],
)
```

### Node inventory — the 28 nodes the graph references

LLM agents (11 — defined in `agents/`):

| Node | Type | Tools / output_key |
|---|---|---|
| `scout` | LlmAgent | 7 pollers; `output_key="candidates"` |
| `triage` | LlmAgent | `memory_bank_search`, `write_state_json` |
| `docs_researcher` | LlmAgent | `web_fetch`, `google_search`; `output_key="docs_research"` |
| `github_researcher` | LlmAgent | `github_get_repo`, `github_get_readme`, `github_list_files`; `output_key="github_research"` |
| `context_researcher` | LlmAgent | `web_fetch`, `google_search`; `output_key="context_research"` |
| `architect_llm` | LlmAgent | none; `output_key="_architect_raw"` (JSON blob, parsed by `architect_split`) |
| `drafter` | LlmAgent | none; `output_key="draft"` |
| `critic_llm` | LlmAgent | none; `output_key="_critic_raw"` (JSON blob) |
| `image_asset_agent` | LlmAgent | `generate_image`, `upload_to_gcs`; one call per `image_briefs` entry |
| `repo_builder` | LlmAgent | `github_create_repo`, `github_commit_files`, `github_set_topics` |
| `revision_writer` | LlmAgent | none; `output_key="draft"` (rewrites the existing draft) |

(Note: video generation is intentionally NOT an LlmAgent in v2 — it lives
in `video_asset_or_skip` as a pure function node. v1's `video_asset_agent`
LlmAgent ignored its prompt-based early-exit guard and called Veo against
a skipped release; v2 makes that bug structurally impossible. See §6.7.)

Function nodes (17 — defined in `nodes/`):

| Node | Subdir | Reads | Writes / Routes |
|---|---|---|---|
| `route_after_triage` | `routing.py` | `chosen_release` | `ctx.route` ∈ `{SKIP, CONTINUE}` |
| `topic_gate_request` | `hitl.py` | `chosen_release` | yields `RequestInput`; posts Telegram message |
| `record_topic_verdict` | `records.py` | (resume input) | `topic_verdict`; for skip, also writes Memory Bank `human-rejected` fact |
| `record_triage_skip` | `records.py` | `skip_reason` | `cycle_outcome="skipped_by_triage"` (terminal) |
| `record_human_topic_skip` | `records.py` | `chosen_release` | `cycle_outcome="skipped_by_human_topic"` (terminal); ensures Memory Bank fact written |
| `record_topic_timeout` | `records.py` | — | `chosen_release=None`, `skip_reason="topic-gate-timeout"`, `cycle_outcome="topic_timeout"` (terminal) |
| `route_topic_verdict` | `routing.py` | `topic_verdict.verdict` | `ctx.route` ∈ `{approve, skip, timeout}` |
| `gather_research` | `aggregation.py` | `docs_research`, `github_research`, `context_research` | `research` (merged dossier) |
| `architect_split` | `architect_split.py` | `_architect_raw` | `outline`, `image_briefs`, `video_brief`, `needs_video`, `needs_repo` (5 keys, replacing v1's callback fan-out) |
| `critic_split` | `critic_split.py` | `_critic_raw`, `writer_iterations` | `draft.critic_feedback`, `draft.critic_verdict`, `writer_iterations` += 1 |
| `route_critic_verdict` | `routing.py` | `draft.critic_verdict`, `writer_iterations` | `ctx.route` ∈ `{REVISE, ACCEPT}`; forces ACCEPT if `writer_iterations >= 3` |
| `video_asset_or_skip` | `video_asset.py` | `needs_video`, `video_brief` | `video_asset` (or None if `needs_video=False`); calls Veo + ffmpeg + GCS only when needed |
| `gather_assets` | `aggregation.py` | `image_assets`, `video_asset` | (no state change; pure barrier node) |
| `route_needs_repo` | `routing.py` | `needs_repo` | `ctx.route` ∈ `{WITH_REPO, WITHOUT_REPO}` |
| `editor_request` | `hitl.py` | `chosen_release`, `draft`, `image_assets`, `video_asset`, `starter_repo` | yields `RequestInput`; posts Telegram message |
| `record_editor_verdict` | `records.py` | (resume input), `editor_iterations` | `editor_verdict`, `human_feedback` (on revise), `editor_iterations` += 1; forces approve/reject if `editor_iterations >= 3` |
| `route_editor_verdict` | `routing.py` | `editor_verdict.verdict` | `ctx.route` ∈ `{approve, reject, revise, timeout}` |
| `record_editor_rejection` | `records.py` | `chosen_release` | `cycle_outcome="rejected_by_editor"` (terminal) |
| `record_editor_timeout` | `records.py` | — | `cycle_outcome="editor_timeout"` (terminal) |
| `publisher` | `publisher.py` | `chosen_release`, `draft`, assets, repo | `final_markdown`, `asset_bundle_url`, `memory_bank_recorded` (writes Memory Bank `covered` fact); `cycle_outcome="published"` (terminal) |

### Routing: why every conditional branch is a function node

In v1, control flow was implicit (a SequentialAgent ran in order; LLM
agents transferred to sub-agents). v2 makes every branch decision a
named function node:

- **Why function nodes for routing instead of LLM agents?** Determinism
  and testability. A function node like `route_critic_verdict` is plain
  Python — `if state.draft.critic_verdict == "accept": ctx.route = "ACCEPT"`.
  We can unit-test that without a model call. v1's `repo_router` was an
  LlmAgent that "decided" whether to invoke the repo builder by reading
  prompt-described state, which works but consumes tokens, can drift,
  and is non-deterministic.
- **Why a separate `record_*` node before/after the route node?**
  Single-responsibility. `record_topic_verdict` is concerned ONLY with
  marshalling the human's response into typed state and (for skip)
  writing the Memory Bank fact. `route_topic_verdict` is concerned ONLY
  with reading the state and emitting `ctx.route`. Splitting makes both
  trivially testable.
- **Why is the writer loop expressed as `route_critic_verdict → drafter`
  instead of `LoopAgent`?** The loop iteration cap belongs in code
  (`writer_iterations` counter), and the verdict-vs-cap decision is a
  routing question. ADK 2.0 has no `LoopAgent` equivalent — graph
  self-edges are the idiom. Cleaner, no special-case primitive.

### Two routing-syntax notes for the implementation

1. **`ctx.route = "BRANCH"` is mandatory** for the dict-edge to follow
   the named branch. `Event(output="BRANCH")` alone does NOT trigger
   conditional routing (spike test #1 surfaced this; ambient sample is
   misleading on this point).
2. **Fan-out is a tuple as the dict-edge value**: `{"approve": (a, b, c)}`
   triggers all three nodes in parallel. They all converge by being the
   `from_node` of edges that target the same join node.

### How nodes are discovered by chunk 4

Each node gets a §6.x subsection in chunk 4 with: inputs (state keys
read), outputs (state keys written, route emitted), tools used (for LLM
agents), failure modes, and test plan. The §6 numbering matches chunk
4's split:

| §6.x | Node group |
|---|---|
| 6.1 | Scout |
| 6.2 | Triage + `route_after_triage` + `record_triage_skip` |
| 6.3 | Topic Gate trio: `topic_gate_request` + `record_topic_verdict` + `route_topic_verdict` + `record_human_topic_skip` + `record_topic_timeout` |
| 6.4 | Research trio + `gather_research` |
| 6.5 | Architect: `architect_llm` + `architect_split` |
| 6.6 | Writer loop: `drafter` + `critic_llm` + `critic_split` + `route_critic_verdict` |
| 6.7 | Assets: `image_asset_agent` + `video_asset_agent` + `gather_assets` |
| 6.8 | Repo: `route_needs_repo` + `repo_builder` |
| 6.9 | Editor: `editor_request` + `record_editor_verdict` + `route_editor_verdict` + `record_editor_rejection` + `record_editor_timeout` |
| 6.10 | Revision Writer (loops back to §6.9) |
| 6.11 | Publisher |

---

## §6 — Per-node specs

§6 documents each of the 28 nodes the Workflow references, in graph
order. Each node entry has the same shape so you can scan it without
re-learning the layout:

- **Type / model / tools / `output_key`** (top metadata)
- **Purpose** (one paragraph — what this node exists for)
- **Inputs** (state keys read; for HITL nodes, the resume input shape)
- **Outputs** (state keys written; route emitted)
- **Behavior** (the algorithm in plain English; for LLM agents, the
  prompt intent — full prompt text lives in `shared/prompts.py`)
- **Failure modes** (every bad outcome we've thought through, with the
  defined recovery)
- **Tests** (the unit + integration tests this node MUST have before
  the workflow can be considered complete)

§6 is split into three chunks for review purposes:
- **chunk 4a** — §6.1 Scout, §6.2 Triage + routing, §6.3 Topic Gate trio
- **chunk 4b** — §6.4 Research, §6.5 Architect, §6.6 Writer loop
- **chunk 4c** — §6.7 Assets, §6.8 Repo, §6.9 Editor, §6.10 Revision Writer, §6.11 Publisher

---

### §6.1 — Scout

| Attribute | Value |
|---|---|
| **Type** | LlmAgent |
| **Model** | `gemini-3.1-flash-lite-preview` |
| **`output_key`** | `candidates` |
| **Tools** | `poll_arxiv`, `poll_github_trending`, `poll_rss`, `poll_hf_models`, `poll_hf_papers`, `poll_hackernews_ai`, `poll_anthropic_news` (7 pollers — verbatim port from working v1 code) |

**Purpose.** First node in the graph. Polls every configured AI release
source, normalizes the results into a single list of `Candidate` dicts,
and writes them to `state.candidates`. Does not score, does not filter
beyond removing obvious non-releases. Triage decides what's worth
covering.

**Inputs:**

| State key | Type | Source | Required? |
|---|---|---|---|
| `last_run_at` | `Optional[datetime]` | Trigger entry node (Cloud Scheduler payload) | No — defaults to `now() - 24h` |

**Outputs:**

| State key | Type | Notes |
|---|---|---|
| `candidates` | `list[Candidate]` | Cap at 25 entries (prefer named-lab posts when capping) |

**Behavior:**

1. Compute `since = last_run_at or (now() - 24h)`. Pass as ISO 8601 string.
2. Call all 7 polling tools concurrently (LlmAgent's parallel function
   calling). If any tool returns `[]`, treat as a normal "quiet window"
   for that source — keep going.
3. Combine results into one flat list. De-dupe by URL.
4. Drop obvious non-releases: job postings, conference recap pages with
   no paper link, generic Hacker News discussion threads with no linked
   artifact.
5. Cap at 25. When capping, **prefer named-lab posts** in this priority
   order: `anthropic > openai > google > deepmind > meta > mistral > nvidia
   > microsoft > arxiv > huggingface_papers > github > huggingface
   > huggingface_blog > bair > hackernews > other`.
6. Emit the list via `output_key="candidates"` (ADK writes it to state).

**Prompt intent (full text in `shared/prompts.py:SCOUT_INSTRUCTION`):**
- Mandate calling EVERY polling tool — Triage depends on coverage.
- Forbid scoring or editorializing; that's Triage's job.
- Define the cap-25 priority order verbatim.
- List every valid `source` value (matches `SourceType` Literal in §4).

**Failure modes:**

| Failure | Recovery |
|---|---|
| All 7 pollers return `[]` (rare — would require simultaneous outage) | `candidates=[]` is written; Triage sees zero candidates and skips with `skip_reason="no candidates this cycle"`. |
| Individual poller raises an exception | The poller's own `try/except` in `tools/pollers.py` catches and returns `[]` (fail-open contract). The LLM should NOT see an exception. |
| LLM cap-priority logic drifts and returns 26+ items | Hard cap at 25 enforced by Triage's input handling — prompt asks for 25 but a function-node guard truncates. (See §6.2 below.) |
| LLM passes `since` as `datetime` object (not ISO string) | Pollers' `_parse_since()` accepts both shapes — already fixed in current code. |
| Network timeout on a single poller | Polled with `HTTP_TIMEOUT_SECONDS=10` per poller; LLM continues with the others. |

**Tests (must exist before this node is "done"):**

- *Unit per-poller* — already exists in `tests/test_scout.py` (25 tests covering all 7 pollers, ISO-string regression, dedup, `since` boundary).
- *Live smoke* — `tests/smoke/pollers_smoke.py` validates ≥10 sources return data against real APIs (currently passing 11/10).
- *Wiring test* — `test_scout_agent_wires_all_pollers` asserts the LlmAgent has all 7 tool names + correct model + correct `output_key`.
- *Cap-25 priority test* — `test_scout_priority_when_capped` (NEW for v2): inject 30 candidates spanning all sources via mocked pollers, assert the 25 returned include all named-lab posts and drop the lowest-priority ones first.

**Open question for chunk 4a review:**
- Should the cap-25 priority be in the prompt (LLM enforces) or in a `nodes/scout_postprocess.py` function node (code enforces)? Code is more reliable but adds a node. **Default in this draft: prompt + a defensive function-node truncation that ALWAYS caps at 25, sorted by priority.** Lets us catch LLM drift without adding a full priority-sort node.

---

### §6.2 — Triage + `route_after_triage` + `record_triage_skip`

This subsection covers three nodes that together handle "did anything
worth covering land in the polling window?".

#### 6.2.1 — `triage` (LlmAgent)

| Attribute | Value |
|---|---|
| **Type** | LlmAgent |
| **Model** | `gemini-3.1-flash` (one tier up from Scout — Triage reasons over scoring rubric + novelty) |
| **`output_key`** | (none — Triage uses `write_state_json` to commit results) |
| **Tools** | `memory_bank_search`, `write_state_json` |

**Purpose.** Pick exactly one candidate from `state.candidates` to write
about, or pick none. The decision is based on (a) a significance score
≥70 AND (b) novelty (not already covered, not already human-rejected).

**Inputs:**

| State key | Type | Required? |
|---|---|---|
| `candidates` | `list[Candidate]` | Yes — Scout's output |

**Outputs (via `write_state_json` tool calls):**

| State key | Type | When |
|---|---|---|
| `chosen_release` | `ChosenRelease` (JSON object) | Exactly one candidate clears the bar |
| `chosen_release` | `null` | Zero candidates clear the bar |
| `skip_reason` | `string` | Always — explains the decision (either "no candidates clear bar: ..." or "winner is X with score N") |

**Behavior:**

1. **For each candidate, compute a significance score (0–100):**
   - Named major lab in `source` (anthropic/openai/google/deepmind/meta/anthropic_news): **+40**
   - New artifact (not a minor patch): **+20**
   - Introduces a capability, SDK, or protocol: **+20**
   - Working code or docs available NOW (URL points at downloadable thing, not a teaser): **+20**
   - (Caps at 100.)
2. **For each candidate that scored ≥70, check novelty:**
   - Call `memory_bank_search(query=f"Have we encountered {title}?", scope="ai_release_pipeline")`.
   - If similarity > 0.85 to any existing fact, drop this candidate.
   - **Pay special attention** to facts tagged `type="human-rejected"` —
     those are HARD rejects (the operator already said no on this exact
     URL or near-duplicate).
3. **Pick the highest-scoring candidate that passed novelty.** Tie-break
   by `published_at` recency.
4. **Persist the decision via `write_state_json`:**
   - Winner case: `write_state_json(key="chosen_release", value_json=<ChosenRelease JSON>)` AND `write_state_json(key="skip_reason", value_json=<short string>)` to provide audit trail.
   - No winner: `write_state_json(key="chosen_release", value_json="null")` AND `write_state_json(key="skip_reason", value_json="<explanation>")`.
5. **Do NOT proceed in prose.** The framework will not parse Triage's
   text output. Only `write_state_json` writes count.

**Prompt intent (full text in `shared/prompts.py:TRIAGE_INSTRUCTION`):**
- Spell out the scoring rubric verbatim (40 + 20 + 20 + 20).
- Mandate `memory_bank_search` per candidate that scored ≥70.
- Force the `human-rejected` fact-type as a HARD reject.
- Forbid prose-only output; require `write_state_json` calls.
- The `skip_reason` string format is free-text but should mention the
  highest-scored candidate even when it didn't clear the bar (helps
  debugging).

**Failure modes:**

| Failure | Recovery |
|---|---|
| Triage writes `chosen_release` as a plain string (not JSON object) | `write_state_json` tool's `_parse_json` rejects with a clear error; LLM is asked to retry. **Already fixed in v1** (Bug B3) — `write_state_json` tolerates plain strings for known-string keys like `skip_reason` but enforces JSON for `chosen_release`. |
| Triage writes `chosen_release` to a release that's already in Memory Bank | Caught by `route_after_triage`'s post-check (see §6.2.3 — defensive re-query). Logs warning, treats as SKIP. |
| Triage produces 0 `write_state_json` calls (LLM ignored instruction) | `route_after_triage` sees `chosen_release` is None (default from `PipelineState`); routes to SKIP with `skip_reason="triage produced no decision"`. |
| `memory_bank_search` returns an error | The tool wrapper catches and returns `[]` — Triage proceeds as if no facts existed (prefer false positives — covering a near-duplicate — over false negatives — silently dropping a real release). |

**Tests:**

- *Score arithmetic* (NEW for v2) — `test_triage_score_named_lab_major_release`: feed a hand-crafted Anthropic release with all four flags set, assert score is 100 in the resulting `chosen_release.score`.
- *Memory Bank novelty* — `test_triage_drops_duplicate_via_memory_bank`: pre-populate memory with a `covered` fact for a URL, feed the same URL as a candidate, assert Triage skips it.
- *Human-rejected hard-reject* — `test_triage_drops_human_rejected_release`: pre-populate memory with a `human-rejected` fact, assert the candidate is skipped even if it would otherwise score 100.
- *Tie-break by recency* — `test_triage_picks_more_recent_when_tied`: two candidates with score 80, assert the newer one wins.
- *Empty candidates* — `test_triage_skips_when_candidates_empty`: feed `candidates=[]`, assert `chosen_release=None` and `skip_reason` is set.
- *Live integration* — `test_triage_against_real_arxiv_window`: skipped without `--live` flag; with the flag, runs Scout + Triage end-to-end against today's polling window.

#### 6.2.2 — `route_after_triage` (function node)

| Attribute | Value |
|---|---|
| **Type** | Function node (in `nodes/routing.py`) |

**Purpose.** Read `chosen_release` and emit `ctx.route` to either `SKIP`
(if None) or `CONTINUE` (if non-None).

**Implementation (the entire function — 8 lines):**

```python
# nodes/routing.py
from google.adk import Context, Event

def route_after_triage(node_input, ctx: Context) -> Event:
    """Decides whether the pipeline continues to Topic Gate or terminates."""
    if ctx.state.get("chosen_release") is None:
        ctx.route = "SKIP"
        return Event(output={"route": "SKIP", "reason": ctx.state.get("skip_reason")})
    ctx.route = "CONTINUE"
    return Event(output={"route": "CONTINUE", "title": ctx.state["chosen_release"]["title"]})
```

**Failure modes:** None — function is total.

**Tests:**

- *route_skip_when_chosen_release_is_none* — assert `ctx.route == "SKIP"` and the output contains `skip_reason`.
- *route_continue_when_chosen_release_set* — assert `ctx.route == "CONTINUE"`.
- *route_handles_missing_chosen_release_key* — defensive: state without the key set should be treated as SKIP (this is what `PipelineState` defaults to, but explicit test guards a refactor mistake).

#### 6.2.3 — `record_triage_skip` (terminal function node)

| Attribute | Value |
|---|---|
| **Type** | Function node (in `nodes/records.py`) |

**Purpose.** Terminal node for the SKIP branch. Sets `cycle_outcome` so
post-cycle reporting knows how this run ended. Does NOT write Memory
Bank — Triage skips are not "operator decisions"; they're algorithmic
filtering, and we don't want to permanently exclude future
re-evaluations of the same candidate.

**Inputs:** `skip_reason` (already set by Triage)

**Outputs:**
- `cycle_outcome = "skipped_by_triage"`
- (Optional) Defensive re-check: if `chosen_release` is somehow non-None
  here (programming error in routing), log loud and force `cycle_outcome
  = "skipped_by_triage"` anyway.

**Implementation:**

```python
# nodes/records.py
def record_triage_skip(node_input, ctx: Context) -> Event:
    if ctx.state.get("chosen_release") is not None:
        # Defensive — if we got here with chosen_release set, the routing
        # is broken. Don't proceed with a confused state.
        logger.error(
            "record_triage_skip reached with chosen_release=%r; routing bug",
            ctx.state["chosen_release"],
        )
    ctx.state["cycle_outcome"] = "skipped_by_triage"
    return Event(output={"outcome": "skipped_by_triage", "reason": ctx.state.get("skip_reason")})
```

**Failure modes:** None — function is total.

**Tests:**

- *records_skipped_by_triage_outcome* — assert `cycle_outcome` is set.
- *defensive_log_when_chosen_release_present* — assert the error log fires (via caplog) when state is inconsistent.

---

### §6.3 — Topic Gate trio (HITL #1)

This is the first human-in-the-loop gate. Five nodes total — all in
`nodes/hitl.py`, `nodes/records.py`, and `nodes/routing.py`.

#### 6.3.1 — `topic_gate_request` (HITL function node)

| Attribute | Value |
|---|---|
| **Type** | Function node (generator — yields `RequestInput`) |
| **File** | `nodes/hitl.py` |
| **Tools called inside** | `telegram.post_topic_approval` |

**Purpose.** Post a Telegram message with three inline-keyboard buttons
(Approve / Skip / Revise — though Revise is not exposed at the Topic
Gate, only Editor; just two buttons here actually: Approve / Skip),
then yield `RequestInput` to pause the workflow until the operator
responds.

**Inputs:**

| State key | Type | Required? |
|---|---|---|
| `chosen_release` | `ChosenRelease` | Yes (guaranteed non-None by `route_after_triage`) |

**Outputs:** None directly. Yields a `RequestInput` event whose
`interrupt_id` becomes the function-call ID for the resume protocol.

**Behavior:**

```python
# nodes/hitl.py
from google.adk import Context
from google.adk.events import RequestInput
from tools.telegram import post_topic_approval

def topic_gate_request(node_input, ctx: Context):
    chosen = ctx.state["chosen_release"]
    interrupt_id = f"topic-gate-{_short_hash(chosen['url'])}"  # ≤30 chars
    # 1. Post Telegram message with buttons keyed by (session_id, interrupt_id, choice).
    post_topic_approval(
        chosen=chosen,
        session_id=ctx.session.id,
        interrupt_id=interrupt_id,
    )
    # 2. Pause for the bridge to resume us with a function_response.
    yield RequestInput(
        interrupt_id=interrupt_id,
        payload=chosen,
        message=(
            f"Topic Gate: approve {chosen['title']!r}? "
            f"(score={chosen['score']}, source={chosen['source']})"
        ),
    )
```

**Why hash the URL into the `interrupt_id`?** Telegram caps `callback_data`
at 64 bytes. Long URLs (especially HuggingFace URLs) overflow. We hash
the URL and store the (short_hash → full_url) mapping in a small
Firestore doc keyed by session — the bridge looks it up on resume.
Detailed in §8 chunk 6.

**Failure modes:**

| Failure | Recovery |
|---|---|
| Telegram API down (network error or 5xx) | `post_topic_approval` raises. The function node propagates; the workflow fails fast. **Recovery option:** wrap the post in a retry-with-backoff (3 attempts, 5s/15s/45s) — added in `tools/telegram.py`. If still failing after retries, the workflow ends with `cycle_outcome="topic_timeout"` and an error log. |
| Telegram bot token invalid (401) | Same as above — fast fail, error log; the operator must rotate the secret. |
| Telegram chat ID wrong (400 chat_not_found) | Same as above. |
| Bridge fails to resume (operator never sees buttons, or buttons don't work) | The `RequestInput` has no built-in timeout in ADK 2.0 — pause is indefinite. We rely on `record_topic_timeout` being driven externally (a separate Cloud Scheduler job that pokes paused sessions older than 24h — see §12). |

**Tests:**

- *topic_gate_request_yields_RequestInput* — call the generator, assert it yields exactly one `RequestInput` with the expected `interrupt_id` shape.
- *topic_gate_request_calls_telegram_post* — mock `post_topic_approval`, assert it's called with the right `chosen`, `session_id`, `interrupt_id`.
- *topic_gate_request_interrupt_id_under_30_chars* — for a worst-case URL (long HF URL), assert `interrupt_id` is ≤30 chars (callback_data budget).

#### 6.3.2 — `record_topic_verdict` (function node)

| Attribute | Value |
|---|---|
| **Type** | Function node |
| **File** | `nodes/records.py` |
| **Tools called inside** | `memory_bank_add_fact` (only on `skip`) |

**Purpose.** Receive the resume input (the operator's button choice),
parse it into a typed `TopicVerdict`, write it to state, and — if the
verdict is `skip` — write a `human-rejected` fact to Memory Bank so
Triage hard-rejects this release on future cycles.

**Inputs:**
- `node_input` — the resume input from the bridge. Shape:
  `{"decision": "approve" | "skip" | "timeout"}`.
- State `chosen_release` — needed to write the Memory Bank fact.

**Outputs:**

| State key | Type | When |
|---|---|---|
| `topic_verdict` | `TopicVerdict` | Always |

Side effect: on `skip`, calls `memory_bank_add_fact(scope="ai_release_pipeline", fact="Human rejected topic: {title}", metadata={"type":"human-rejected", "release_url":..., "release_source":..., "rejected_at":...})`.

**Implementation:**

```python
# nodes/records.py
from datetime import datetime, timezone
from google.adk import Context, Event
from shared.models import TopicVerdict
from shared.memory import memory_bank_add_fact

def record_topic_verdict(node_input, ctx: Context) -> Event:
    decision = _coerce_decision(node_input)  # "approve" | "skip" | "timeout"
    ctx.state["topic_verdict"] = TopicVerdict(
        verdict=decision, at=datetime.now(timezone.utc)
    )
    if decision == "skip":
        chosen = ctx.state["chosen_release"]
        memory_bank_add_fact(
            scope="ai_release_pipeline",
            fact=f"Human rejected topic: {chosen['title']}",
            metadata={
                "type": "human-rejected",
                "release_url": chosen["url"],
                "release_source": chosen["source"],
                "rejected_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    return Event(output={"verdict": decision})
```

**Failure modes:**

| Failure | Recovery |
|---|---|
| `node_input` shape unexpected (e.g. plain string instead of dict) | `_coerce_decision` handles both shapes (dict or string); falls back to `"timeout"` if neither parses. |
| Memory Bank write fails on the `skip` branch | Log error; do NOT fail the workflow — the Topic Gate skip is the operator's primary signal, the Memory Bank fact is a secondary artifact. The next cycle MAY surface the same release; operator can skip again. |

**Tests:**

- *coerces_dict_decision_to_TopicVerdict* — feed `{"decision": "approve"}`, assert `state.topic_verdict.verdict == "approve"`.
- *coerces_string_decision_to_TopicVerdict* — feed `"skip"` as a raw string, assert it becomes `verdict="skip"`.
- *writes_memory_bank_fact_on_skip* — mock memory bank; assert called with `type="human-rejected"`.
- *no_memory_bank_write_on_approve* — mock memory bank; assert not called.
- *no_memory_bank_write_on_timeout* — mock memory bank; assert not called.
- *memory_bank_write_failure_does_not_kill_node* — make memory bank raise; assert function still returns the verdict event without raising.

#### 6.3.3 — `route_topic_verdict` (function node)

| Attribute | Value |
|---|---|
| **Type** | Function node |
| **File** | `nodes/routing.py` |

**Purpose.** Read `topic_verdict.verdict` and emit `ctx.route` so the
dict-edge can pick the right next step.

**Implementation (5 lines):**

```python
# nodes/routing.py
def route_topic_verdict(node_input, ctx: Context) -> Event:
    decision = ctx.state["topic_verdict"].verdict
    ctx.route = decision  # "approve" | "skip" | "timeout"
    return Event(output={"route": decision})
```

**Failure modes:** None — `topic_verdict` is guaranteed non-None by
upstream `record_topic_verdict`.

**Tests:** Three trivial tests, one per route value.

#### 6.3.4 — `record_human_topic_skip` (terminal function node)

| Attribute | Value |
|---|---|
| **Type** | Terminal function node |
| **File** | `nodes/records.py` |

**Purpose.** Terminal node for the human-skip branch. Memory Bank fact
was already written by `record_topic_verdict`; this node only sets
`cycle_outcome`.

**Implementation:**

```python
def record_human_topic_skip(node_input, ctx: Context) -> Event:
    ctx.state["cycle_outcome"] = "skipped_by_human_topic"
    return Event(output={"outcome": "skipped_by_human_topic"})
```

**Tests:** One — assert `cycle_outcome` set.

#### 6.3.5 — `record_topic_timeout` (terminal function node)

| Attribute | Value |
|---|---|
| **Type** | Terminal function node |
| **File** | `nodes/records.py` |

**Purpose.** Terminal node for the timeout branch. Clears `chosen_release`
(so future cycles can re-attempt this release; no permanent rejection),
sets `skip_reason`, and `cycle_outcome`.

**Implementation:**

```python
def record_topic_timeout(node_input, ctx: Context) -> Event:
    ctx.state["chosen_release"] = None
    ctx.state["skip_reason"] = "topic-gate-timeout"
    ctx.state["cycle_outcome"] = "topic_timeout"
    return Event(output={"outcome": "topic_timeout"})
```

**Why clear `chosen_release` on timeout but NOT write to Memory Bank?**
Because timeout ≠ rejection. The operator might have been asleep; the
release is still potentially worth covering. We clear `chosen_release`
so the cycle ends cleanly, and we don't write to Memory Bank so the
next cycle can re-surface the same release.

**Tests:**
- *clears_chosen_release_on_timeout* — assert it's None after.
- *sets_skip_reason* — assert string equals `"topic-gate-timeout"`.
- *sets_cycle_outcome* — assert `"topic_timeout"`.
- *does_not_write_memory_bank* — mock memory bank; assert no calls.

---

### Summary table — chunk 4a node count

| § | Nodes documented | LLM agents | Function nodes |
|---|---|---|---|
| 6.1 | scout | 1 | 0 |
| 6.2 | triage, route_after_triage, record_triage_skip | 1 | 2 |
| 6.3 | topic_gate_request, record_topic_verdict, route_topic_verdict, record_human_topic_skip, record_topic_timeout | 0 | 5 |
| **Total chunk 4a** | **9 nodes** | **2** | **7** |

19 nodes remain (9 LLM agents + 10 function nodes) — chunks 4b and 4c.

### Five decisions baked in chunk 4a worth challenging

1. **Cap-25 priority is enforced both in prompt AND in a defensive
   function-node truncation.** Belt + suspenders. (§6.1 open question)
2. **`memory_bank_add_fact` is called from `record_topic_verdict`, not
   from a separate node.** Compactness over single-responsibility — the
   write is logically tied to the verdict capture. (§6.3.2)
3. **Triage uses `gemini-3.1-flash`, not `flash-lite`** — one tier up
   from Scout because the rubric arithmetic + novelty reasoning is
   non-trivial. v1 used the same model. Push back if you want flash-lite
   to save cost.
4. **`record_topic_timeout` clears `chosen_release` to None, allowing
   future cycles to re-surface the same release.** Alternative: write
   a `topic-gate-timeout` Memory Bank fact with a TTL to suppress
   re-surfacing for N days. **Default in v2: no TTL fact, allow
   re-surface.** Push back if you want suppression.
5. **`interrupt_id` for Topic Gate is `f"topic-gate-{short_hash(url)}"`,
   stable across retries.** This means if the same URL surfaces twice
   in close succession (e.g. duplicate Pub/Sub trigger), both pause-IDs
   collide. We use this collision deliberately — the second trigger
   "joins" the first paused session rather than racing. (Connects to
   Goal 4 idempotency in §2.) Push back if you want unique-per-attempt.

---

### §6.4 — Researcher pool + `gather_research`

This subsection covers four nodes — three parallel LLM agents that
research the chosen release from different angles, plus one function
node that joins their outputs.

The three researchers are deliberately separate (not one mega-agent)
because:
- Each has a distinct tool set (the GitHub researcher needs PyGithub;
  the others need `web_fetch` + `google_search`).
- Failures are independent — if GitHub's rate limit kicks in, the docs
  researcher should still run.
- They can run in parallel — the graph fans them out from
  `route_topic_verdict`'s `approve` branch and joins them at
  `gather_research`.

#### 6.4.1 — `docs_researcher` (LlmAgent)

| Attribute | Value |
|---|---|
| **Type** | LlmAgent |
| **Model** | `gemini-3.1-flash` |
| **`output_key`** | `docs_research` |
| **Tools** | `web_fetch`, `google_search` (built-in ADK tool) |

**Purpose.** Fetch the official documentation, blog post, or release
notes for `chosen_release` and produce a structured `ResearchDossier`
the Architect and Writer can build from.

**Inputs:**

| State key | Type | Required? |
|---|---|---|
| `chosen_release` | `ChosenRelease` | Yes (guaranteed non-None by upstream routing) |

**Outputs:**

| State key | Type | Notes |
|---|---|---|
| `docs_research` | `ResearchDossier` | Structured dossier; fields below |

**Behavior:**

1. Read `chosen_release.url`. If it points at official docs / release blog,
   call `web_fetch` directly. Otherwise use `google_search` to locate the
   canonical landing page first, then `web_fetch` it.
2. If the landing page references a quickstart / tutorial / changelog, fetch
   those too (max 3 additional pages, to keep token cost bounded).
3. Extract into a `ResearchDossier`:
   - `summary`: 1 paragraph, ≤120 words, of what the release is + does.
   - `headline_quotes`: up to 2 verbatim quotes from official sources
     suitable for pull-quotes in the article.
   - `code_example`: ONE minimal code snippet that demonstrates the
     headline capability. Markdown fenced. Optional (None if no
     runnable code is appropriate).
   - `prerequisites`: list of strings — what a reader needs installed
     or signed up for before the snippet works.
4. Other dossier fields (`repo_meta`, `readme_excerpt`, `file_list`,
   `reactions`, `related_releases`) stay None — those are filled by the
   GitHub and Context researchers.
5. Emit via `output_key="docs_research"`.

**Prompt intent (in `shared/prompts.py:DOCS_RESEARCHER_INSTRUCTION`):**
- Mandate the structured fields with type expectations.
- Cap `summary` at 120 words and `code_example` at 30 lines.
- Forbid speculation: every claim in `summary` must trace to a fetched
  page (cite via inline URL in the dossier `summary` field).

**Failure modes:**

| Failure | Recovery |
|---|---|
| `chosen_release.url` returns 404 or non-HTML | Fall back to `google_search` for the title; if no canonical page found, write a minimal dossier with `summary="Could not locate official source for {title}"` so the Architect can still produce SOME outline. |
| `web_fetch` exceeds token budget (oversize HTML) | `tools/web.py` caps response at 200KB; LLM gets truncated content. Acceptable lossy fetch. |
| Google Search quota exceeded | Tool returns error; LLM falls back to using only `chosen_release.raw_summary` (Scout already collected this). Dossier degrades gracefully. |

**Tests:**

- *Wiring* — `test_docs_researcher_has_correct_tools`, `_has_correct_output_key`, `_uses_flash_model`.
- *Prompt loaded verbatim* — `test_docs_researcher_instruction_loaded`.
- *Early-exit absent* — v2 does NOT need the `if state['chosen_release'] is None` early-exit; the routing already guards. Test asserts the prompt does NOT contain the v1 preamble.
- *Live integration (skipped without `--live` flag)* — feed a real Anthropic post URL, assert dossier has non-empty `summary` and at least one `headline_quotes` entry.

#### 6.4.2 — `github_researcher` (LlmAgent)

| Attribute | Value |
|---|---|
| **Type** | LlmAgent |
| **Model** | `gemini-3.1-flash-lite-preview` (deterministic fetch + format) |
| **`output_key`** | `github_research` |
| **Tools** | `github_get_repo`, `github_get_readme`, `github_list_files` |

**Purpose.** When `chosen_release.url` (or any URL extractable from the
release context) points at a GitHub repo, fetch repo metadata, the
README, and a top-level file list. Otherwise, write an empty dossier.

**Inputs:** `chosen_release`

**Outputs:** `github_research: ResearchDossier`

**Behavior:**

1. Determine target repo:
   - If `chosen_release.url` matches `github.com/{owner}/{repo}/?...`,
     use `{owner}/{repo}`.
   - If `chosen_release.source == "github"`, the URL IS a repo URL.
   - Else, **skip** — write `github_research = ResearchDossier(summary="No GitHub repo associated with this release.")` and end.
2. Call `github_get_repo({owner}/{repo})` for stars/forks/last_push.
3. Call `github_get_readme({owner}/{repo})` for the README.
4. Call `github_list_files({owner}/{repo}, ref="HEAD")` for the top-level
   file list (cap at 50 entries).
5. Populate dossier:
   - `summary`: 1 sentence — "{owner}/{repo}: {N} stars, last pushed {date}, language {lang}."
   - `repo_meta`: dict with stars, forks, language, last_push, default_branch.
   - `readme_excerpt`: first 1500 chars of README.
   - `file_list`: top-level paths.

**Prompt intent (in `shared/prompts.py:GITHUB_RESEARCHER_INSTRUCTION`):**
- Mandate the empty-dossier shortcut when the release isn't on GitHub.
- Forbid creating placeholder repo URLs or guessing the repo from the
  release name.

**Failure modes:**

| Failure | Recovery |
|---|---|
| `chosen_release` has no GitHub URL | Empty dossier (described above). Not a failure. |
| Repo is private (404 from API) | `github_get_repo` returns `{"error": "..."}`; LLM writes empty dossier with `summary="Repository is private or inaccessible."` |
| Rate limit exhaustion | Tool returns `{"error": "rate limit"}`; LLM emits empty dossier; pipeline continues. |
| README is binary / very large | `github_get_readme` truncates to 100KB; LLM uses what it gets. |

**Tests:**

- *URL-detection* — `test_github_researcher_skips_non_github_release`.
- *Empty dossier shape* — assert `summary` non-empty even when skipping.
- *Wiring* — tools, model, output_key.

#### 6.4.3 — `context_researcher` (LlmAgent)

| Attribute | Value |
|---|---|
| **Type** | LlmAgent |
| **Model** | `gemini-3.1-flash` |
| **`output_key`** | `context_research` |
| **Tools** | `web_fetch`, `google_search` |

**Purpose.** Build the "world around this release" — what came before
(prior versions, related releases from competitors), how the community
is reacting (Hacker News threads, Reddit, X mentions if surfaced via
search), and any prerequisite context the reader needs.

**Inputs:** `chosen_release`

**Outputs:** `context_research: ResearchDossier`

**Behavior:**

1. Search for "{title} reactions" and "{title} comparison" via
   `google_search`. Pick top 3 results that are NOT the release's own
   landing page (de-dupe by domain vs `chosen_release.url`).
2. `web_fetch` each, extract:
   - `reactions`: list of brief (≤80 char) "platform: paraphrase" lines.
     E.g. "HN: 'finally a real autonomy library, not just a wrapper.'"
   - `related_releases`: list of titles or product names (e.g.
     "OpenAI Agents SDK", "LangChain Agents") with one-sentence
     positioning vs the chosen release.
3. Populate dossier:
   - `summary`: 1 paragraph of "what's the landscape this release
     enters?".
   - `reactions`, `related_releases`: as above.

**Prompt intent (`shared/prompts.py:CONTEXT_RESEARCHER_INSTRUCTION`):**
- Forbid quoting reactions verbatim if no source can be cited
  (paraphrase + cite domain only).
- Cap `reactions` at 5 entries, `related_releases` at 5.
- Forbid claims of "first-of-kind" without specific competitor citations.

**Failure modes:**

| Failure | Recovery |
|---|---|
| Google Search returns no relevant results | Empty `reactions` and `related_releases`; `summary="No community context found yet — this release is too fresh for reactions to have surfaced."` |
| All `web_fetch` calls error | Same as above — empty dossier with explanation summary. |

**Tests:** Wiring, prompt-loaded, empty-dossier graceful degradation.

#### 6.4.4 — `gather_research` (function node)

| Attribute | Value |
|---|---|
| **Type** | Function node |
| **File** | `nodes/aggregation.py` |

**Purpose.** Pure barrier node. Reads the three researcher dossiers and
merges them into a single `research: ResearchDossier` for downstream
nodes (Architect, Writer) to consume. Triggers AFTER all three
researchers complete (graph join semantics).

**Inputs:** `docs_research`, `github_research`, `context_research`

**Outputs:** `research: ResearchDossier`

**Implementation (the entire function — 25 lines):**

```python
# nodes/aggregation.py
from google.adk import Context, Event
from shared.models import ResearchDossier

def gather_research(node_input, ctx: Context) -> Event:
    """Merge three per-source dossiers into one."""
    docs    = ctx.state.get("docs_research")    or _empty()
    gh      = ctx.state.get("github_research")  or _empty()
    context = ctx.state.get("context_research") or _empty()

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

def _empty() -> ResearchDossier:
    return ResearchDossier(summary="")
```

**Failure modes:**

| Failure | Recovery |
|---|---|
| All three researcher dossiers are missing (would mean upstream graph bug) | Use `_empty()` for each → merged dossier has empty fields → Architect downstream produces a degraded outline but workflow continues. Defensive log if all three are None. |
| Researchers produced conflicting `summary` strings | Use `docs > context > github` priority. Architect can read `summary` from the source dossiers in `state` if needed. |

**Tests:**

- *Merges all three filled dossiers correctly* — assert each owner's fields land in the right slot.
- *Handles all-empty case* — feed three `None`s, assert merged dossier exists with empty fields.
- *Priority for conflicting summaries* — feed three different `summary` strings, assert docs wins.

### Decisions to challenge — chunk 4b §6.4

1. **Researchers run in parallel via the dict-edge fan-out
   `{"approve": (docs, github, context)}`** rather than wrapped in a
   `ParallelAgent`. Direct, fewer abstractions, but a different mental
   model from v1. Push back if you'd rather keep `ParallelAgent` for
   familiarity.
2. **`github_researcher` is the only researcher allowed to short-circuit
   to an empty dossier** (no GitHub repo associated). The other two
   always do their best to produce content — even if that means
   "no community context found yet". Explicit non-symmetry.
3. **`gather_research` is a pure barrier** — does NOT call any LLM. The
   Architect downstream is responsible for prioritizing/weighing the
   merged dossier. Splits "merge structure" from "merge meaning."

---

### §6.5 — Architect: `architect_llm` + `architect_split`

This pair is the v2 replacement for v1's "Architect agent + after-agent
callback that parses a JSON blob." Same intent, but the parser is a
named, testable, type-safe function node.

#### 6.5.1 — `architect_llm` (LlmAgent)

| Attribute | Value |
|---|---|
| **Type** | LlmAgent |
| **Model** | `gemini-3.1-pro` (heaviest model — Architect's output drives all downstream content) |
| **`output_key`** | `_architect_raw` |
| **Tools** | none |

**Purpose.** Read `chosen_release` + the merged `research` dossier;
produce a structured plan for the article: outline (sections), image
briefs (≥1 hero + 1–3 inline), optional video brief, and two boolean
decisions (`needs_video`, `needs_repo`).

**Inputs:**

| State key | Type | Required? |
|---|---|---|
| `chosen_release` | `ChosenRelease` | Yes |
| `research` | `ResearchDossier` | Yes |

**Outputs:**

| State key | Type | Notes |
|---|---|---|
| `_architect_raw` | `str` | A single JSON blob with the keys below; parsed by `architect_split` |

**Expected JSON shape (this is the contract `architect_split` parses):**

```json
{
  "outline": {
    "working_title": "...",
    "working_subtitle": "...",
    "article_type": "quickstart" | "explainer" | "comparison" | "release_recap",
    "sections": [
      {"heading": "...", "intent": "...", "research_items": ["...", "..."], "word_count": 250}
    ]
  },
  "image_briefs": [
    {"position": "hero", "description": "...", "style": "illustration", "aspect_ratio": "16:9"},
    {"position": "section_2", "description": "...", "style": "diagram", "aspect_ratio": "16:9"}
  ],
  "video_brief": {
    "description": "...",
    "style": "...",
    "duration_seconds": 6,
    "aspect_ratio": "16:9"
  },
  "needs_video": true,
  "needs_repo": false
}
```

**Behavior (algorithm in plain English):**

1. Read `chosen_release.{title, source, raw_summary, score, rationale}`
   and `research.{summary, headline_quotes, code_example, prerequisites,
   repo_meta, readme_excerpt, reactions, related_releases}`.
2. Pick `article_type` based on `research.code_example`:
   - Has runnable code AND prerequisites → `quickstart`.
   - Has reactions / related_releases > 1 → `comparison`.
   - Has clear single-product narrative → `release_recap`.
   - Otherwise → `explainer`.
3. Generate 4–6 sections with section-level word counts summing to
   800–1200 (article-type-specific defaults).
4. Generate 2–4 image briefs:
   - Always exactly 1 with `position="hero"`, `aspect_ratio="16:9"`,
     `style="illustration"`.
   - 1–3 inline images with `position="section_N"` matching outline
     section indices.
5. Decide `needs_video`:
   - `needs_video=true` iff `article_type ∈ {quickstart, release_recap}`
     AND there's a "show, don't tell" moment (UI demo, animation, or
     terminal walkthrough). Default: `false`.
6. Decide `needs_repo`:
   - `needs_repo=true` iff `article_type=="quickstart"` AND
     `research.code_example` is non-None AND
     `len(research.prerequisites) >= 2`.
7. If `needs_video=true`, populate `video_brief` (else null).
8. Return the complete JSON blob.

**Prompt intent (`shared/prompts.py:ARCHITECT_INSTRUCTION`):**
- The blob's keys MUST match `PipelineState`'s field names exactly.
- The blob MUST be a single JSON object (no markdown fences, no prose).
- All `image_briefs` entries MUST have `aspect_ratio="16:9"` (Medium
  default; v3 may add 4:3).
- `needs_video` defaults to `false` — the LLM must justify any `true`
  with a specific "show, don't tell" moment described in the
  corresponding `video_brief.description`.

**Failure modes:**

| Failure | Recovery |
|---|---|
| LLM emits prose alongside JSON | `architect_split` strips markdown fences and pulls the first `{...}` block; logs a warning. |
| LLM emits invalid JSON | `architect_split` raises; the workflow fails fast (we'd rather see a clear error than partial state). Future enhancement: 1 retry with corrective system message. |
| LLM uses wrong field names (e.g. `subtitle` instead of `working_subtitle`) | Pydantic `Outline` model rejects → workflow fails fast. |
| LLM emits 0 image_briefs or 0 sections | Pydantic / a custom validator in `architect_split` rejects → fails fast. |
| LLM emits >4 image_briefs | `architect_split` truncates to 4, logs warning (Imagen quota protection). |

**Tests:**

- *Prompt mandates the JSON shape* — assert `ARCHITECT_INSTRUCTION` contains every required field name.
- *Wiring* — model is `gemini-3.1-pro`, `output_key="_architect_raw"`, no tools.
- *Live integration (skipped)* — feed a real chosen_release + dossier, assert the JSON parses into a valid `Outline + image_briefs + ...` set.

#### 6.5.2 — `architect_split` (function node)

| Attribute | Value |
|---|---|
| **Type** | Function node |
| **File** | `nodes/architect_split.py` |

**Purpose.** Parse `_architect_raw` (the LLM's JSON blob) into 5 typed
state writes: `outline`, `image_briefs`, `video_brief`, `needs_video`,
`needs_repo`. **This replaces v1's `after_agent_callback` JSON-blob
parser** and is testable in isolation.

**Inputs:** `_architect_raw: str`

**Outputs:**
- `outline: Outline`
- `image_briefs: list[ImageBrief]`
- `video_brief: Optional[VideoBrief]`
- `needs_video: bool`
- `needs_repo: bool`

**Implementation (~50 lines):**

```python
# nodes/architect_split.py
import json, logging, re
from google.adk import Context, Event
from shared.models import (
    Outline, ImageBrief, VideoBrief, OutlineSection,
)

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

def architect_split(node_input, ctx: Context) -> Event:
    raw = ctx.state.get("_architect_raw") or ""
    cleaned = _FENCE_RE.sub("", raw).strip()
    # Best-effort: extract first {...} block if there's prose around it.
    if not cleaned.startswith("{"):
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError(f"architect produced no JSON: {raw[:200]!r}")
        cleaned = match.group(0)

    try:
        blob = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise ValueError(f"architect JSON invalid: {e}; raw={raw[:200]!r}") from e

    # Outline (validated by Pydantic)
    outline = Outline(**blob["outline"])
    if not outline.sections:
        raise ValueError("architect produced 0 sections")

    # Image briefs
    image_briefs = [ImageBrief(**b) for b in blob.get("image_briefs", [])]
    if not image_briefs:
        raise ValueError("architect produced 0 image_briefs")
    if len(image_briefs) > 4:
        logger.warning("architect produced %d image_briefs; truncating to 4",
                       len(image_briefs))
        image_briefs = image_briefs[:4]
    if not any(b.position == "hero" for b in image_briefs):
        raise ValueError("architect did not produce a hero image_brief")

    # Video brief — optional, gated by needs_video
    needs_video = bool(blob.get("needs_video", False))
    vb_dict = blob.get("video_brief")
    video_brief = VideoBrief(**vb_dict) if (needs_video and vb_dict) else None
    if needs_video and video_brief is None:
        logger.warning("needs_video=true but no video_brief; coercing needs_video=false")
        needs_video = False

    needs_repo = bool(blob.get("needs_repo", False))

    # Atomic state write
    ctx.state["outline"]      = outline
    ctx.state["image_briefs"] = image_briefs
    ctx.state["video_brief"]  = video_brief
    ctx.state["needs_video"]  = needs_video
    ctx.state["needs_repo"]   = needs_repo
    return Event(output={
        "sections": len(outline.sections),
        "images": len(image_briefs),
        "needs_video": needs_video,
        "needs_repo": needs_repo,
    })
```

**Failure modes:**

| Failure | Recovery |
|---|---|
| `_architect_raw` is empty | Raises `ValueError`; workflow fails fast. |
| JSON unparseable (LLM wrote prose) | Best-effort regex extracts first `{...}`; if none found, raises `ValueError`. |
| Outline has 0 sections | Raises (covered above). |
| 0 image_briefs | Raises. |
| No hero image_brief | Raises (forces LLM to comply via prompt + this guard). |
| `needs_video=true` but no `video_brief` | Coerce `needs_video=false` and log warning. Defensive — Asset Agent's video early-exit reads `needs_video`. |
| Pydantic validation fails on a sub-model | Raises with a clear field-level error from Pydantic. |

**Tests:**

- *Happy path* — feed a hand-crafted complete blob, assert all 5 state keys are written with correct shapes.
- *Markdown fences are stripped* — wrap the JSON in `\`\`\`json … \`\`\``, assert it still parses.
- *Prose-around-JSON is recovered* — prefix with "Here is your plan: {…}", assert the JSON still parses.
- *Empty `_architect_raw` raises* — assert `ValueError`.
- *Invalid JSON raises* — assert `ValueError` with the partial raw included.
- *0 sections raises*.
- *0 image_briefs raises*.
- *Missing hero image_brief raises*.
- *needs_video=true with no video_brief is coerced to false* — assert `needs_video == False` and warning log.
- *>4 image_briefs is truncated to 4* — assert and warning log.

### Decisions to challenge — chunk 4b §6.5

1. **Architect uses `gemini-3.1-pro`** — the heaviest model in the
   pipeline. v1 used the same. Cost-saving alternative: try `flash`
   first, escalate to `pro` only on JSON-validation failures. Defer
   to "cost optimization" non-goal in §2.
2. **`architect_split` raises on every structural error** (invalid JSON,
   0 sections, 0 image_briefs, no hero) instead of attempting a 1-shot
   LLM retry with a corrective system message. **Default in v2: fast
   fail.** Push back if you want the corrective-retry pattern.
3. **`needs_video` defaults to `false` if `video_brief` is missing** —
   silent coercion (with warning log). Alternative: raise. Defaulting
   to false matches the "Veo defaults to off" non-goal from §2.
4. **The architect prompt does NOT show the LLM the full
   `PipelineState` schema** — only describes the JSON shape. Risk: LLM
   field names could drift. **Mitigation: a unit test that pulls field
   names from `Outline.__fields__` and asserts they appear verbatim in
   the prompt.** Prevents drift without coupling the prompt to a
   generated schema.

---

### §6.6 — Writer loop: `drafter` + `critic_llm` + `critic_split` + `route_critic_verdict`

The writer loop is the v2 replacement for v1's `LoopAgent`. It's a
graph self-edge — `route_critic_verdict` either continues to assets or
loops back to `drafter`, with a hard cap of 3 iterations enforced in
`route_critic_verdict` itself.

#### 6.6.1 — `drafter` (LlmAgent)

| Attribute | Value |
|---|---|
| **Type** | LlmAgent |
| **Model** | `gemini-3.1-pro` (long-form prose generation) |
| **`output_key`** | `draft` |
| **Tools** | none |

**Purpose.** Generate a Markdown article matching `outline`. On
iteration 0, write from scratch using `outline + research`. On
iterations 1–2, rewrite the existing `draft` per `draft.critic_feedback`.

**Inputs:**

| State key | Type | Required? |
|---|---|---|
| `outline` | `Outline` | Yes |
| `research` | `ResearchDossier` | Yes |
| `chosen_release` | `ChosenRelease` | Yes |
| `image_briefs` | `list[ImageBrief]` | Yes (drafter inserts placeholder image markers `<!--IMG:hero-->` at the right positions) |
| `draft` | `Optional[Draft]` | Only on iterations ≥1 — read for previous markdown + critic_feedback |
| `writer_iterations` | `int` | Yes — drafter behaves differently on iteration 0 vs 1+ |

**Outputs:**

| State key | Type | Notes |
|---|---|---|
| `draft` | `Draft` | New `Draft(markdown=..., iteration=writer_iterations, critic_feedback=None, critic_verdict=None)` |

**Behavior:**

1. Read `writer_iterations`.
2. **If `writer_iterations == 0`**: write the full article from scratch.
   - Use `outline.working_title`, `outline.working_subtitle`, and each
     `outline.sections[i]` as section H2s.
   - Insert image placeholders `<!--IMG:{position}-->` at section
     boundaries matching `image_briefs[i].position`.
   - Insert video placeholder `<!--VID:hero-->` after the hero image
     iff `needs_video=True`.
   - Word count target: sum of `outline.sections[i].word_count`.
3. **If `writer_iterations > 0`**: rewrite the previous `draft.markdown`
   addressing `draft.critic_feedback`. Preserve image / video markers.
4. Emit a new `Draft` via `output_key="draft"` with `iteration =
   writer_iterations` (**before** `critic_split` increments it),
   `critic_feedback=None`, `critic_verdict=None`.

**Prompt intent (`shared/prompts.py:DRAFTER_INSTRUCTION`):**
- Mandate Markdown-only output (no JSON wrapper).
- Mandate `<!--IMG:{position}-->` and `<!--VID:hero-->` placeholders.
- Forbid the LLM from filling in actual image URLs (those are inserted
  by Publisher after assets land).
- On rewrites, preserve all image / video markers from the previous
  draft unless `critic_feedback` explicitly asks to add or remove one.

**Failure modes:**

| Failure | Recovery |
|---|---|
| LLM emits a JSON wrapper instead of plain Markdown | `Draft.markdown` becomes the raw text; the Critic / Publisher will see the malformed shape and route to REVISE → drafter retries. |
| LLM forgets image placeholders on rewrite | `critic_split` checks for placeholder count vs `len(image_briefs)`; if mismatch, sets `critic_verdict="revise"` with feedback "preserve image markers". |
| LLM produces a draft far over word count (e.g. 3x target) | Critic catches in next pass and asks for trim. |
| LLM produces empty markdown | `critic_split` treats empty draft as a forced `revise` with feedback "draft was empty". After 3 iterations, `route_critic_verdict` forces ACCEPT — but Publisher will then reject with a clear error since the draft is empty. |

**Tests:**

- *Wiring* — model, `output_key="draft"`, no tools.
- *Iteration 0 receives only outline+research, not previous draft* — assert prompt template fills only those keys.
- *Iteration 1+ receives previous draft + critic_feedback* — assert prompt includes both.
- *Output is a Draft with `iteration=writer_iterations`* — assert via mock.
- *Image placeholders preserved on rewrite* — feed a draft with `<!--IMG:hero-->` + critic_feedback "shorten intro", assert rewritten draft still contains the placeholder.

#### 6.6.2 — `critic_llm` (LlmAgent)

| Attribute | Value |
|---|---|
| **Type** | LlmAgent |
| **Model** | `gemini-3.1-flash` (rubric-checking, not generative) |
| **`output_key`** | `_critic_raw` |
| **Tools** | none |

**Purpose.** Score the current `draft` against a rubric and return a
structured verdict (accept or revise + feedback).

**Inputs:**

| State key | Type | Required? |
|---|---|---|
| `draft` | `Draft` | Yes |
| `outline` | `Outline` | Yes (rubric needs the working title + section count to compare) |
| `image_briefs` | `list[ImageBrief]` | Yes (rubric checks placeholder count) |
| `needs_video` | `bool` | Yes |
| `writer_iterations` | `int` | Read for context but does NOT factor into verdict (the cap lives in `route_critic_verdict`) |

**Outputs:**

| State key | Type | Notes |
|---|---|---|
| `_critic_raw` | `str` | JSON blob: `{"verdict": "accept" \| "revise", "feedback": "..."}` |

**Rubric (in `shared/prompts.py:CRITIC_INSTRUCTION`):**

The Critic emits `verdict="revise"` if ANY of these fail:
1. Word count is within ±20% of `outline.sections[*].word_count` sum.
2. Each `outline.sections[i].heading` appears as an H2 in the draft (in order).
3. Image placeholder count == `len(image_briefs)`, with positions matching.
4. Video placeholder present iff `needs_video=true`.
5. The `chosen_release.title` appears in the draft (proves the article
   is about the right thing).
6. No `<!--IMG:` or `<!--VID:` markers reference positions not in
   `image_briefs` / `video_brief`.
7. The intro reads at a 7th-grade level (heuristic — Critic estimates).
8. There are no factual claims that don't trace to the `research`
   dossier.

If all 8 pass → `verdict="accept"`, `feedback="".`

**Behavior:** The LLM receives the draft + rubric + research and emits
a single-line JSON verdict. No tool calls.

**Failure modes:**

| Failure | Recovery |
|---|---|
| LLM emits `verdict` that's neither "accept" nor "revise" | `critic_split` coerces to `"revise"` with feedback "critic verdict was unparseable: {raw}". |
| LLM emits prose | `critic_split`'s JSON extractor handles markdown fences + first-{...}; if no JSON found, treats as forced revise. |
| LLM falsely accepts a draft missing all image placeholders | `critic_split` does an OBJECTIVE check (string-search for placeholder markers) and OVERRIDES the LLM's `accept` with `revise` if placeholders are missing. **Belt + suspenders for Bug B2 class.** |

**Tests:** Rubric items as individual tests (feed a draft that fails
each item, assert critic returns revise with appropriate feedback).

#### 6.6.3 — `critic_split` (function node)

| Attribute | Value |
|---|---|
| **Type** | Function node |
| **File** | `nodes/critic_split.py` |

**Purpose.** Parse `_critic_raw` into typed `draft.critic_feedback` and
`draft.critic_verdict`; increment `writer_iterations`. **Also performs
the objective placeholder check** (overrides LLM accept → revise if
markers are wrong).

**Inputs:** `_critic_raw`, `draft`, `image_briefs`, `needs_video`,
`writer_iterations`

**Outputs:**
- `draft.critic_feedback`, `draft.critic_verdict` (mutates the existing
  Draft in state)
- `writer_iterations` += 1

**Implementation (~40 lines):**

```python
# nodes/critic_split.py
import json, re
from google.adk import Context, Event
from shared.models import Draft

_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)

def critic_split(node_input, ctx: Context) -> Event:
    raw = ctx.state.get("_critic_raw") or ""
    cleaned = _FENCE_RE.sub("", raw).strip()
    if not cleaned.startswith("{"):
        m = re.search(r"\{.*\}", cleaned, re.DOTALL)
        cleaned = m.group(0) if m else "{}"
    try:
        blob = json.loads(cleaned)
    except json.JSONDecodeError:
        blob = {}

    verdict = blob.get("verdict", "revise")
    if verdict not in ("accept", "revise"):
        verdict = "revise"
    feedback = blob.get("feedback", "") or ""

    # Objective placeholder check — overrides LLM accept if markers wrong.
    draft: Draft = ctx.state["draft"]
    image_marker_re = re.compile(r"<!--IMG:([^>]+?)-->", re.IGNORECASE)
    video_marker_re = re.compile(r"<!--VID:[^>]+?-->", re.IGNORECASE)
    image_briefs = ctx.state.get("image_briefs", [])
    needs_video = ctx.state.get("needs_video", False)

    image_markers = image_marker_re.findall(draft.markdown)
    if len(image_markers) != len(image_briefs):
        verdict = "revise"
        feedback = (
            f"objective check: draft has {len(image_markers)} image markers, "
            f"expected {len(image_briefs)}. {feedback}"
        ).strip()

    has_video_marker = bool(video_marker_re.search(draft.markdown))
    if has_video_marker != needs_video:
        verdict = "revise"
        feedback = (
            f"objective check: video marker presence ({has_video_marker}) "
            f"does not match needs_video ({needs_video}). {feedback}"
        ).strip()

    # Mutate draft + bump iteration counter
    draft.critic_feedback = feedback
    draft.critic_verdict = verdict
    ctx.state["draft"] = draft
    ctx.state["writer_iterations"] = ctx.state.get("writer_iterations", 0) + 1
    return Event(output={
        "verdict": verdict,
        "iteration": ctx.state["writer_iterations"],
        "feedback_preview": feedback[:120],
    })
```

**Failure modes:** All handled inline (graceful degradation).

**Tests:**

- *Parses valid JSON verdict*.
- *Coerces unparseable JSON to revise*.
- *Coerces unknown verdict value to revise*.
- *Objective placeholder count mismatch overrides LLM accept*.
- *Video marker mismatch overrides LLM accept*.
- *Increments writer_iterations*.
- *Mutates draft.critic_feedback and verdict*.

#### 6.6.4 — `route_critic_verdict` (function node)

| Attribute | Value |
|---|---|
| **Type** | Function node |
| **File** | `nodes/routing.py` |

**Purpose.** Read `draft.critic_verdict` and `writer_iterations`, emit
`ctx.route` to either `REVISE` (loops back to drafter) or `ACCEPT`
(continues to assets). **Forces ACCEPT at iteration 3** to prevent
infinite loops.

**Implementation (10 lines):**

```python
# nodes/routing.py
def route_critic_verdict(node_input, ctx: Context) -> Event:
    iteration = ctx.state.get("writer_iterations", 0)
    verdict = ctx.state["draft"].critic_verdict
    if iteration >= 3:
        ctx.route = "ACCEPT"
        return Event(output={"route": "ACCEPT", "forced": True, "iteration": iteration})
    ctx.route = "ACCEPT" if verdict == "accept" else "REVISE"
    return Event(output={"route": ctx.route, "forced": False, "iteration": iteration})
```

**Failure modes:** None — function is total.

**Tests:**

- *route_REVISE_when_critic_says_revise_below_cap*.
- *route_ACCEPT_when_critic_says_accept_below_cap*.
- *forces_ACCEPT_at_iteration_3_even_with_revise_verdict*.
- *forces_ACCEPT_at_iteration_4_etc* (defensive — should never reach 4 but test confirms).

### Decisions to challenge — chunk 4b §6.6

1. **Hard cap is 3 iterations** (drafter runs at most 3 times). v1 had
   the same cap. Tunable via the constant `MAX_WRITER_ITERATIONS = 3`
   in `nodes/routing.py`.
2. **`critic_split` performs objective placeholder checks INSIDE the
   parser** (not in a separate node). Compactness over single-
   responsibility. Alternative: a `critic_objective_check` function
   between critic_llm and critic_split.
3. **Drafter receives `image_briefs` so it can place markers**, but
   does NOT receive `image_assets` (URLs). The Publisher inserts URLs
   later. Separation of concerns: Drafter owns prose layout; Publisher
   owns final asset injection.
4. **No "critic accepts but Publisher rejects" feedback path.** If the
   draft is structurally broken at Publisher time, the cycle ends with
   `cycle_outcome="rejected_by_editor"` (Editor catches it) — we don't
   loop back to drafter from Publisher. Simpler; rare path.

---

### §6.7 — Assets: `image_asset_agent` + `video_asset_or_skip` + `gather_assets`

Three nodes total. The image side keeps an LlmAgent (alt-text generation
benefits from LLM). The video side is **a function node** — Veo
generation is deterministic given a brief, and v1's prompt-based
"if needs_video=False, end your turn" guard was the bug Bug B2 produced.
We fix the bug class by removing the LLM, not by writing a stricter prompt.

#### 6.7.1 — `image_asset_agent` (LlmAgent)

| Attribute | Value |
|---|---|
| **Type** | LlmAgent |
| **Model** | `gemini-3.1-flash` (alt-text writing + per-brief prompt augmentation; not heavy reasoning) |
| **`output_key`** | `image_assets` |
| **Tools** | `generate_image` (Imagen wrapper), `upload_to_gcs` |

**Purpose.** For each entry in `image_briefs`, generate the image via
Imagen, upload to GCS, write a per-image `alt_text`, and accumulate
into `image_assets`.

**Inputs:**

| State key | Type | Required? |
|---|---|---|
| `image_briefs` | `list[ImageBrief]` | Yes (Architect produces ≥1) |
| `chosen_release` | `ChosenRelease` | Yes (used to enrich Imagen prompt with project context) |

**Outputs:**

| State key | Type | Notes |
|---|---|---|
| `image_assets` | `list[ImageAsset]` | One per `image_briefs` entry, in the same order |

**Behavior:**

1. For each `brief` in `image_briefs` (sequentially — Imagen has per-call
   quota that's easier to manage serially):
   - Compose a richer prompt:
     `f"{brief.style} of {brief.description} (context: {chosen_release.title})"`.
   - Call `generate_image(prompt=..., aspect_ratio=brief.aspect_ratio,
     style=brief.style)` → returns image bytes.
   - Generate a slug: `f"{cycle_id}/{brief.position}.png"`.
   - Call `upload_to_gcs(payload=bytes, slug=slug, content_type="image/png")`
     → returns public HTTPS URL.
   - Generate `alt_text`: 1 sentence describing the image content for
     screen readers. LLM-generated.
   - Construct `ImageAsset(position=brief.position, url=..., alt_text=...,
     aspect_ratio=brief.aspect_ratio)`.
2. Emit the full list via `output_key="image_assets"`.

**Prompt intent (`shared/prompts.py:IMAGE_ASSET_INSTRUCTION`):**
- Mandate calling `generate_image` exactly once per brief.
- Mandate calling `upload_to_gcs` exactly once per generated image.
- Mandate emitting `image_assets` as a list with the same length as
  `image_briefs`, in the same order.
- alt_text MUST describe what's in the image — NOT what the article
  is about. (Accessibility correctness.)

**Failure modes:**

| Failure | Recovery |
|---|---|
| Imagen returns 404 (model not available in region) | Tool's wrapper logs and returns `None`; LLM emits a placeholder `ImageAsset(url="", alt_text="(image generation failed)")`. Editor can revise/reject if assets are critical. |
| Imagen quota exceeded mid-batch | Same as above per-brief; partial `image_assets` list with placeholders for failed entries. |
| `upload_to_gcs` fails | Same per-brief — placeholder. |
| LLM emits fewer ImageAssets than briefs | `gather_assets` defensive check raises with a clear error pointing at this node; the cycle terminates as `cycle_outcome="rejected_by_editor"` (Editor sees the broken state and rejects). |

**Tests:**

- *Wiring* — model, tools, `output_key`.
- *One generate_image per brief* — mock both tools, feed 3 image_briefs, assert 3 calls each.
- *alt_text is non-empty for each generated asset*.
- *Imagen failure produces a placeholder rather than aborting* — mock to fail on the 2nd brief, assert 1 real + 1 placeholder + 1 real (the 3rd still attempted).

#### 6.7.2 — `video_asset_or_skip` (function node)

| Attribute | Value |
|---|---|
| **Type** | Function node (NOT LlmAgent — see chunk header for rationale) |
| **File** | `nodes/video_asset.py` |
| **Tools called inside** | `generate_video`, `convert_to_gif`, `extract_first_frame`, `upload_to_gcs` |

**Purpose.** When `needs_video=True`, generate a Veo clip from `video_brief`,
derive a GIF + poster from the MP4, upload all three to GCS, and write
`video_asset`. When `needs_video=False`, write `video_asset=None` and
return immediately — **NO Veo call, no token cost, no LLM in the loop**.

**Inputs:**

| State key | Type | Required? |
|---|---|---|
| `needs_video` | `bool` | Yes (the guard) |
| `video_brief` | `Optional[VideoBrief]` | Yes if `needs_video=True` |

**Outputs:**

| State key | Type | Notes |
|---|---|---|
| `video_asset` | `Optional[VideoAsset]` | None when skipped; `VideoAsset(mp4_url, gif_url, poster_url, duration_seconds)` otherwise |

**Implementation (~40 lines):**

```python
# nodes/video_asset.py
import logging
from google.adk import Context, Event
from shared.models import VideoAsset
from tools.veo import generate_video
from tools.video_processing import convert_to_gif, extract_first_frame
from tools.gcs import upload_to_gcs

logger = logging.getLogger(__name__)

def video_asset_or_skip(node_input, ctx: Context) -> Event:
    """Generate the optional video asset, OR skip cleanly if not needed.

    The needs_video guard is enforced HERE in code — there is no LLM in
    this node, so prompt-following bugs (v1 Bug B2) are structurally
    impossible.
    """
    if not ctx.state.get("needs_video"):
        ctx.state["video_asset"] = None
        return Event(output={"skipped": True, "reason": "needs_video=False"})

    brief = ctx.state.get("video_brief")
    if brief is None:
        # Defensive — architect_split should have coerced needs_video=False
        # if no brief was produced. Log and skip gracefully.
        logger.warning("video_asset_or_skip: needs_video=True but video_brief is None; skipping")
        ctx.state["video_asset"] = None
        return Event(output={"skipped": True, "reason": "no video_brief despite needs_video=True"})

    cycle_id = ctx.session.id[:8]
    try:
        mp4_bytes = generate_video(
            prompt=brief.description,
            duration_seconds=brief.duration_seconds,
            aspect_ratio=brief.aspect_ratio,
        )
    except Exception as e:
        logger.warning("Veo generation failed: %s — leaving video_asset=None", e)
        ctx.state["video_asset"] = None
        return Event(output={"skipped": True, "reason": f"veo_error: {e}"})

    mp4_url    = upload_to_gcs(payload=mp4_bytes, slug=f"{cycle_id}/video.mp4",   content_type="video/mp4")
    gif_bytes  = convert_to_gif(mp4_bytes)
    gif_url    = upload_to_gcs(payload=gif_bytes, slug=f"{cycle_id}/video.gif",   content_type="image/gif")
    poster_bytes = extract_first_frame(mp4_bytes)
    poster_url = upload_to_gcs(payload=poster_bytes, slug=f"{cycle_id}/poster.jpg", content_type="image/jpeg")

    ctx.state["video_asset"] = VideoAsset(
        mp4_url=mp4_url, gif_url=gif_url, poster_url=poster_url,
        duration_seconds=brief.duration_seconds,
    )
    return Event(output={"skipped": False, "duration_seconds": brief.duration_seconds})
```

**Failure modes:**

| Failure | Recovery |
|---|---|
| `needs_video=False` | Return immediately with `video_asset=None`. Cost: 0. |
| `needs_video=True` but `video_brief=None` (architect bug) | Log warning, skip gracefully with `video_asset=None`. |
| Veo 404 / quota / timeout | Catch, log, set `video_asset=None`, continue pipeline. We do NOT fail the cycle on Veo errors — the article is still publishable without the video. |
| `convert_to_gif` or `extract_first_frame` ffmpeg error | Same — catch, log, set `video_asset=None`. (These are inside the try/except after Veo; if Veo succeeded but ffmpeg fails, we lose the video. Acceptable rare path.) |
| `upload_to_gcs` fails | Same — catch, log, set `video_asset=None`. |

**Tests:**

- *skip_when_needs_video_is_False* — assert tools NOT called; `video_asset=None`.
- *skip_when_video_brief_missing_despite_needs_video_true* — assert tools NOT called; warning logged.
- *full_path_when_needs_video_true* — mock all 3 GCS uploads + Veo + ffmpeg, assert `video_asset` is populated with all 3 URLs.
- *veo_error_does_not_kill_cycle* — make `generate_video` raise; assert function returns Event with `skipped: True, reason: veo_error: ...` and `video_asset=None`.
- *ffmpeg_error_after_veo_success_sets_video_asset_none* — mock Veo to succeed but `convert_to_gif` to raise; assert `video_asset=None` and warning logged.
- **Bug B2 regression test** — `test_video_asset_or_skip_does_not_call_veo_when_chosen_release_is_None` — set up state where upstream routing should have prevented us from getting here, AND `needs_video=True` from a stale state. Assert Veo is still NOT called because the guard checks `needs_video` first. (Defense-in-depth — even if upstream routing breaks, we don't waste a Veo call.)

#### 6.7.3 — `gather_assets` (function node)

| Attribute | Value |
|---|---|
| **Type** | Function node (pure barrier) |
| **File** | `nodes/aggregation.py` |

**Purpose.** Pure barrier node. Triggers AFTER both
`image_asset_agent` and `video_asset_or_skip` complete (graph join).
Performs invariant checks; emits a summary event.

**Inputs:** `image_assets`, `video_asset`, `image_briefs` (for the
length-match check)

**Outputs:** None to state (pure barrier).

**Implementation (15 lines):**

```python
# nodes/aggregation.py (continued from gather_research)
def gather_assets(node_input, ctx: Context) -> Event:
    image_assets = ctx.state.get("image_assets", [])
    image_briefs = ctx.state.get("image_briefs", [])
    video_asset  = ctx.state.get("video_asset")
    needs_video  = ctx.state.get("needs_video", False)

    if len(image_assets) != len(image_briefs):
        # Defensive — image_asset_agent should have produced one per brief.
        logger.error(
            "gather_assets: %d image_assets but %d image_briefs",
            len(image_assets), len(image_briefs),
        )

    return Event(output={
        "image_count": len(image_assets),
        "video_present": video_asset is not None,
        "needs_video":   needs_video,
    })
```

**Failure modes:**

| Failure | Recovery |
|---|---|
| Asset count mismatch (image_briefs vs image_assets) | Log error; do NOT raise. The Editor will see the malformed asset list when it composes the Telegram preview and the operator can choose to revise. |

**Tests:**

- *Logs error on count mismatch* — feed 3 briefs but 2 assets, assert log captured.
- *Output reports correct counts*.
- *Output reports needs_video correctly*.

### Decisions to challenge — chunk 4c §6.7

1. **`video_asset_or_skip` is a function node, not an LlmAgent** —
   biggest design change in chunk 4c. Eliminates the entire Bug B2
   class. Cost: lose LLM-augmented Veo prompts (the architect_llm
   already wrote `video_brief.description`, so this is fine).
2. **`image_asset_agent` REMAINS an LlmAgent** for alt-text generation.
   Push back if you want to also flatten this into a function node and
   write alt-text via a templated heuristic. Tradeoff: heuristic
   alt-text is worse for accessibility.
3. **Imagen failures produce placeholder ImageAssets, NOT aborts.** The
   Editor sees them and can decide whether to revise or reject. v1's
   default was to fail the cycle on any Imagen error — too aggressive.
4. **`gather_assets` only LOGS the count mismatch, doesn't raise.**
   The Editor is the next downstream HITL — let the human decide
   whether to ship a draft with broken images. Push back if you'd
   rather hard-fail at this barrier.

---

### §6.8 — Repo router + Repo Builder

Two nodes — `route_needs_repo` and `repo_builder`. The router is a
3-line function; the builder is the LlmAgent that actually creates and
populates a starter GitHub repo.

#### 6.8.1 — `route_needs_repo` (function node)

| Attribute | Value |
|---|---|
| **Type** | Function node |
| **File** | `nodes/routing.py` |

**Purpose.** Read `needs_repo` and emit `ctx.route` to either
`WITH_REPO` (call the repo builder) or `WITHOUT_REPO` (skip directly to
the Editor).

**Implementation (5 lines):**

```python
def route_needs_repo(node_input, ctx: Context) -> Event:
    needs = bool(ctx.state.get("needs_repo", False))
    ctx.route = "WITH_REPO" if needs else "WITHOUT_REPO"
    return Event(output={"route": ctx.route, "needs_repo": needs})
```

**Failure modes:** None.

**Tests:** Two — one per route value.

#### 6.8.2 — `repo_builder` (LlmAgent)

| Attribute | Value |
|---|---|
| **Type** | LlmAgent |
| **Model** | `gemini-3.1-flash` (deterministic file generation, not heavy reasoning) |
| **`output_key`** | `starter_repo` |
| **Tools** | `github_create_repo`, `github_commit_files`, `github_set_topics` |

**Purpose.** Create a public GitHub repo named after the chosen release
(e.g. `airel-quickstart-{slug}`), commit a starter file set (README +
the code_example from research), and set repository topics. Persist
the resulting URL + commit SHA to `state.starter_repo`.

**Inputs:**

| State key | Type | Required? |
|---|---|---|
| `chosen_release` | `ChosenRelease` | Yes |
| `research` | `ResearchDossier` | Yes (for code_example, prerequisites) |
| `outline` | `Outline` | Yes (for working_title — used as repo description) |
| `draft` | `Draft` | Yes (markdown becomes the README) |
| `image_assets` | `list[ImageAsset]` | Yes (referenced as image URLs in README, not committed as files) |

**Outputs:**

| State key | Type | Notes |
|---|---|---|
| `starter_repo` | `StarterRepo` | url, files_committed list, sha |

**Behavior:**

1. Compute repo name: `f"airel-{outline.article_type}-{slugify(chosen_release.title)}"`
   capped at 100 chars (GitHub limit). Truncate slugified title if
   needed.
2. Call `github_create_repo(name=..., description=outline.working_title,
   private=False)` under the configured org (`GITHUB_ORG` env var).
3. Compose starter file set:
   - `README.md` — full markdown of `draft.markdown`, with
     `<!--IMG:...-->` placeholders replaced by their `image_assets[i].url`.
   - `examples/quickstart.py` (or `.ts`, etc., depending on
     `research.code_example` language) — verbatim from
     `research.code_example`.
   - `requirements.txt` (or `package.json`) — generated from
     `research.prerequisites` if it lists Python packages.
   - `.gitignore` — language-default template.
4. Call `github_commit_files(repo=name, files=<list of (path,
   content)>, message=f"Initial commit for {chosen_release.title}",
   source_url=...)` — atomic multi-file commit via the Git Data API.
5. Call `github_set_topics(repo=name, topics=[chosen_release.source,
   "ai-release-pipeline", outline.article_type])`.
6. Emit `StarterRepo(url=..., files_committed=[...], sha=...)`.

**Prompt intent (`shared/prompts.py:REPO_BUILDER_INSTRUCTION`):**
- Mandate calling all three tools in order.
- Forbid creating placeholder repo URLs without actually calling
  `github_create_repo`.
- Image URL substitution in README: pattern `<!--IMG:{position}-->` →
  `![{alt_text}]({url})`.
- Repo name slug rules (lowercase, hyphens only, ≤100 chars).

**Failure modes:**

| Failure | Recovery |
|---|---|
| `github_create_repo` 422 (name conflict — repo already exists) | LLM appends `-{cycle_id_short}` and retries once. If still fails, write `starter_repo=None` and continue (Editor will see `needs_repo=True` but `starter_repo=None` and can revise/reject). |
| GitHub PAT lacks `repo` scope (401/403) | Fast fail; the cycle ends with `cycle_outcome="rejected_by_editor"` (Editor sees the missing repo). Operator must rotate the PAT. |
| Org doesn't exist or PAT lacks org admin (404) | Same as above. |
| `github_commit_files` partial failure (some files committed, others not) | Tool wrapper is atomic — Git Data API commits all-or-nothing; either every file is in the SHA or none are. No partial state. |
| `github_set_topics` failure (rate limit) | Log warning; do NOT fail the node — the repo and files are already committed. Topics are cosmetic. |

**Tests:**

- *Wiring* — model, tools, `output_key="starter_repo"`.
- *Repo name slugification* — feed a chosen_release with special chars + spaces, assert the repo name is lowercase + hyphenated + ≤100 chars.
- *Image URL substitution in README* — feed a draft with `<!--IMG:hero-->` and image_assets with a URL, assert the README that's committed has `![alt](url)` instead of the placeholder.
- *Starter file set composition* — feed a quickstart with code_example=python and prerequisites=[anthropic, requests], assert files_committed includes README.md, examples/quickstart.py, requirements.txt.
- *Name conflict triggers single retry with cycle_id_short suffix*.
- *Failure to create repo writes starter_repo=None and does not raise* — pipeline continues to Editor.

### Decisions to challenge — chunk 4c §6.8

1. **Repos are PUBLIC by default.** Reason: the article links to them as
   "starter projects readers can fork." Private repos defeat the
   purpose. Push back if you'd rather make them private and let the
   operator manually flip them on approval.
2. **Repo name format is `airel-{article_type}-{slug}`.** Caps at 100
   chars. Push back if you want a different naming convention (e.g.
   `pixelcanon/{slug}` or include a date).
3. **No language detection beyond what `research.code_example` exposes.**
   If the code is JavaScript, we expect `research.code_example` to be
   tagged with `js`. If it's not, we default to `.py`. Push back if you
   want a smarter detector.
4. **No CI / GitHub Actions starter** committed. The repo is a content
   skeleton, not a working project. Operator can add CI manually if they
   want. v3 candidate.

---

### §6.9 — Editor trio + decision-recorder + timeout terminal (HITL #2)

This subsection covers the second human-in-the-loop gate. **Five nodes
total** — same shape as §6.3's Topic Gate. Operator sees the draft, the
asset URLs, and the optional repo URL; chooses approve / revise / reject
(or times out).

#### 6.9.1 — `editor_request` (HITL function node)

| Attribute | Value |
|---|---|
| **Type** | Function node (generator — yields `RequestInput`) |
| **File** | `nodes/hitl.py` |
| **Tools called inside** | `telegram.post_editor_review` |

**Purpose.** Post a Telegram message with three buttons (Approve /
Revise / Reject) showing the operator: title, draft preview (first 500
chars), image URLs, video URL (if present), repo URL (if present).
Then yield `RequestInput`. On Revise, the bridge collects free-text
feedback via Telegram's `ForceReply` mechanism.

**Inputs:**

| State key | Type | Required? |
|---|---|---|
| `chosen_release` | `ChosenRelease` | Yes |
| `draft` | `Draft` | Yes |
| `image_assets` | `list[ImageAsset]` | Yes |
| `video_asset` | `Optional[VideoAsset]` | Optional |
| `starter_repo` | `Optional[StarterRepo]` | Optional |

**Outputs:** None directly. Yields `RequestInput`.

**Behavior:**

```python
# nodes/hitl.py (continued)
def editor_request(node_input, ctx: Context):
    chosen   = ctx.state["chosen_release"]
    draft    = ctx.state["draft"]
    images   = ctx.state.get("image_assets", [])
    video    = ctx.state.get("video_asset")
    repo     = ctx.state.get("starter_repo")
    interrupt_id = f"editor-{ctx.session.id[:8]}-{ctx.state.get('editor_iterations', 0)}"
    # Note: editor interrupt_id includes iteration so revise loops produce
    # distinct IDs (so the bridge can disambiguate which revision the
    # button tap is for).

    post_editor_review(
        chosen=chosen,
        draft_preview=draft.markdown[:500],
        image_urls=[img.url for img in images],
        video_url=(video.gif_url if video else None),
        repo_url=(repo.url if repo else None),
        session_id=ctx.session.id,
        interrupt_id=interrupt_id,
    )
    yield RequestInput(
        interrupt_id=interrupt_id,
        payload={"draft_iteration": draft.iteration, "editor_iterations": ctx.state.get("editor_iterations", 0)},
        message=f"Editor: {chosen['title']!r} — approve, revise, or reject?",
    )
```

**Why include `editor_iterations` in the `interrupt_id`?** Because the
revision loop may pause + resume multiple times on the same release.
Without iteration in the ID, the bridge can't distinguish "approve the
1st draft" from "approve the 2nd draft after revision."

**Failure modes:** Same as `topic_gate_request` (§6.3.1) — Telegram
network/auth failures; bridge resume failures.

**Tests:**

- *yields_RequestInput_with_iteration_in_interrupt_id*.
- *includes_repo_url_when_starter_repo_present*.
- *omits_repo_url_when_starter_repo_None*.
- *includes_video_url_when_video_asset_present*.
- *draft_preview_is_first_500_chars*.

#### 6.9.2 — `record_editor_verdict` (function node)

| Attribute | Value |
|---|---|
| **Type** | Function node |
| **File** | `nodes/records.py` |

**Purpose.** Receive the resume input (operator's choice + optional
free-text revision feedback), parse into typed `EditorVerdict`, write
to state, increment `editor_iterations`, AND **enforce the iteration
cap** (force decision at iteration 3).

**Inputs:**
- `node_input` — resume input shape: `{"decision": "approve" | "reject" | "revise" | "timeout", "feedback": "<optional, only on revise>"}`
- State `editor_iterations`, `chosen_release`

**Outputs:**
- `editor_verdict: EditorVerdict`
- `human_feedback: Optional[RevisionFeedback]` (set only on revise)
- `editor_iterations` += 1

**Implementation:**

```python
# nodes/records.py (continued)
from datetime import datetime, timezone
from shared.models import EditorVerdict, RevisionFeedback

MAX_EDITOR_ITERATIONS = 3

def record_editor_verdict(node_input, ctx: Context) -> Event:
    decision, feedback = _coerce_editor_response(node_input)
    iter_count = ctx.state.get("editor_iterations", 0) + 1

    # Iteration cap — force terminal decision at the cap.
    if iter_count > MAX_EDITOR_ITERATIONS and decision == "revise":
        logger.warning(
            "Editor revise requested at iteration %d > cap %d — forcing reject.",
            iter_count, MAX_EDITOR_ITERATIONS,
        )
        decision = "reject"
        feedback = (feedback or "") + " [forced reject: revision cap reached]"

    now = datetime.now(timezone.utc)
    ctx.state["editor_verdict"] = EditorVerdict(
        verdict=decision, feedback=feedback, at=now,
    )
    if decision == "revise":
        ctx.state["human_feedback"] = RevisionFeedback(feedback=feedback or "", at=now)
    ctx.state["editor_iterations"] = iter_count
    return Event(output={
        "verdict": decision,
        "iteration": iter_count,
        "has_feedback": bool(feedback),
    })
```

**Failure modes:**

| Failure | Recovery |
|---|---|
| `decision="revise"` but no feedback string | `human_feedback` is set with an empty string; revision_writer detects empty feedback and rewrites with a generic "improve clarity and concision" instruction. Logged. |
| Iteration cap exceeded | Forced to `reject` with appended note. Operator sees the rejection and can re-trigger if they want another shot. |
| Unknown decision value | `_coerce_editor_response` falls back to `"timeout"`. Defensive. |

**Tests:**

- *records_approve*, *records_reject*, *records_revise_with_feedback*, *records_timeout*.
- *increments_editor_iterations_each_call*.
- *forces_reject_on_revise_at_iteration_4* — pre-set `editor_iterations=3`, send "revise"; assert `editor_verdict.verdict == "reject"`.
- *human_feedback_set_only_on_revise*.
- *empty_feedback_on_revise_logs_warning*.

#### 6.9.3 — `route_editor_verdict` (function node)

| Attribute | Value |
|---|---|
| **Type** | Function node |
| **File** | `nodes/routing.py` |

**Purpose.** Read `editor_verdict.verdict` and emit `ctx.route`.

**Implementation (3 lines):**

```python
def route_editor_verdict(node_input, ctx: Context) -> Event:
    decision = ctx.state["editor_verdict"].verdict
    ctx.route = decision
    return Event(output={"route": decision})
```

**Failure modes:** None.

**Tests:** Four — one per route value.

#### 6.9.4 — `record_editor_rejection` (terminal function node)

| Attribute | Value |
|---|---|
| **Type** | Terminal function node |
| **File** | `nodes/records.py` |

**Purpose.** Terminal node for the reject branch. Sets `cycle_outcome`.
Does NOT write Memory Bank — Editor rejection is more nuanced than
Topic Gate skip (the operator may have rejected because of the *draft
quality*, not because of the release itself).

**Implementation:**

```python
def record_editor_rejection(node_input, ctx: Context) -> Event:
    ctx.state["cycle_outcome"] = "rejected_by_editor"
    return Event(output={
        "outcome": "rejected_by_editor",
        "feedback": ctx.state["editor_verdict"].feedback,
    })
```

**Tests:** One — assert `cycle_outcome` set.

**Decision flagged for chunk 6 (HITL contract):** Should Editor
rejection write a Memory Bank fact? **Default in v2: NO** (rejection
might be about draft, not release). Operator can manually skip future
re-surfacings via Topic Gate. Push back if you want auto-write.

#### 6.9.5 — `record_editor_timeout` (terminal function node)

| Attribute | Value |
|---|---|
| **Type** | Terminal function node |
| **File** | `nodes/records.py` |

**Purpose.** Terminal node for the timeout branch. Symmetric to
§6.3.5's `record_topic_timeout` — does NOT write Memory Bank, allows
re-surface.

**Implementation:**

```python
def record_editor_timeout(node_input, ctx: Context) -> Event:
    ctx.state["cycle_outcome"] = "editor_timeout"
    return Event(output={"outcome": "editor_timeout"})
```

**Tests:** One.

### Decisions to challenge — chunk 4c §6.9

1. **Editor iteration cap = 3** (same as writer loop). Forced `reject`
   at iteration 4. Operator can re-trigger the cycle if they want
   another shot. Tunable via `MAX_EDITOR_ITERATIONS`.
2. **`interrupt_id` includes `editor_iterations`** so the bridge can
   disambiguate "approve revision N" from "approve revision N+1." Topic
   Gate doesn't need this (only one chance to vote on the topic).
3. **Editor rejection does NOT write Memory Bank.** Reason: the
   rejection might be about draft quality, not the release. Push back
   if you want auto-write — the resulting bias is "if a draft is bad,
   we never re-attempt the release." For polished v2 we want
   re-attempts to be possible.
4. **Free-text feedback comes via Telegram's `ForceReply`** (forces a
   threaded reply). Bridge captures the reply text and packages it into
   the `FunctionResponse` payload. Detailed in §8 chunk 6.

---

### §6.10 — `revision_writer` (LlmAgent)

One node — the LLM that rewrites the draft per `human_feedback`. Loops
back into `editor_request` (§6.9.1) for re-review.

| Attribute | Value |
|---|---|
| **Type** | LlmAgent |
| **Model** | `gemini-3.1-pro` (long-form rewrite — same tier as drafter) |
| **`output_key`** | `draft` |
| **Tools** | none |

**Purpose.** Rewrite the existing `draft.markdown` to address the
operator's `human_feedback`. Preserve image / video markers and
section structure unless feedback explicitly asks to change them.

**Inputs:**

| State key | Type | Required? |
|---|---|---|
| `draft` | `Draft` | Yes (current draft to rewrite) |
| `human_feedback` | `RevisionFeedback` | Yes (the operator's instruction) |
| `outline` | `Outline` | Yes (rewrite must still satisfy the outline) |
| `image_briefs` | `list[ImageBrief]` | Yes (placeholder count must remain) |
| `chosen_release` | `ChosenRelease` | Yes (subject of the article) |

**Outputs:**

| State key | Type | Notes |
|---|---|---|
| `draft` | `Draft` | New `Draft(markdown=<rewritten>, iteration=draft.iteration + 1, critic_feedback=None, critic_verdict=None)` |

**Behavior:**

1. Read `draft.markdown` + `human_feedback.feedback`.
2. Apply the feedback while preserving:
   - Section headings (H2s) from `outline.sections[*].heading`.
   - All `<!--IMG:...-->` and `<!--VID:...-->` markers.
   - Total word count within ±20% of `outline.sections[*].word_count`
     sum (unless feedback explicitly says "shorten" or "expand").
3. Emit a new Draft via `output_key="draft"`. Increment `iteration`.

**Prompt intent (`shared/prompts.py:REVISION_WRITER_INSTRUCTION`):**
- Mandate Markdown-only output (same as Drafter).
- Mandate marker preservation (same as Drafter rewrite path).
- Forbid adding "v1.1" / "Updated:" / "Revised:" notices in the prose —
  the rewrite is opaque to readers.
- If `human_feedback.feedback` is empty (operator hit Revise with no
  text), apply a default: "improve clarity and concision throughout."

**Failure modes:**

| Failure | Recovery |
|---|---|
| LLM ignores feedback (rewrites identically) | The Editor will see the same draft on the next pass, will likely Revise again, and the iteration cap kicks in. Acceptable degradation. |
| LLM removes image / video markers | Loops back to `editor_request`. The Editor preview will look broken (no images in preview); operator likely revises with explicit "preserve image markers" — OR rejects. |
| LLM produces empty rewrite | Editor sees blank, rejects. Cap-3 iteration limit prevents infinite loop. |

**Tests:**

- *Wiring* — model, tools, `output_key`.
- *Iteration is incremented* — feed draft.iteration=2, assert output draft.iteration=3.
- *Markers preserved unless feedback asks to remove them* — feed `human_feedback="shorten intro"`, assert image/video markers still in rewritten draft.
- *Empty feedback applies default instruction* — feed `human_feedback.feedback=""`, assert prompt includes "improve clarity and concision".
- *Critic feedback is cleared on rewrite* — assert new draft has `critic_feedback=None` and `critic_verdict=None` (so the Critic re-reviews on next Writer-loop pass... wait, no — revision_writer goes back to editor_request, NOT to critic. So this field doesn't matter for revision. Test simply asserts the new draft is well-formed.)

### Decisions to challenge — chunk 4c §6.10

1. **`revision_writer` loops back to `editor_request`, not to `critic_llm`.**
   Once the Editor is involved, the Critic's structural rubric is
   bypassed — the Editor's human judgment supersedes. v1 had the same
   behavior. Push back if you want the Critic to re-review revisions
   before the human sees them.
2. **`revision_writer` increments `draft.iteration`.** Total iterations
   across writer-loop AND revision loop are tracked on the same field.
   Feels right semantically; verify under §15 if any reporting depends
   on the distinction.

---

### §6.11 — `publisher` (function node, terminal)

The terminal node for the happy path. Composes the final article + asset
bundle, writes the Memory Bank `covered` fact, sets `cycle_outcome`.

| Attribute | Value |
|---|---|
| **Type** | Function node (terminal) |
| **File** | `nodes/publisher.py` |
| **Tools called inside** | `medium_format`, `upload_to_gcs`, `memory_bank_add_fact` |

**Purpose.**
1. Inject image and video URLs into `draft.markdown` (replace
   `<!--IMG:position-->` markers with `![alt_text](url)`).
2. Run the Medium-friendly markdown post-processor.
3. Bundle the final markdown + asset URLs (and starter_repo URL if
   present) into a single GCS object for downstream consumption.
4. Write the Memory Bank `covered` fact so Triage hard-rejects this
   release on future cycles.
5. Set `cycle_outcome="published"` and `memory_bank_recorded=True`.

**Inputs:**

| State key | Type | Required? |
|---|---|---|
| `chosen_release` | `ChosenRelease` | Yes |
| `draft` | `Draft` | Yes |
| `image_assets` | `list[ImageAsset]` | Yes |
| `video_asset` | `Optional[VideoAsset]` | Optional |
| `starter_repo` | `Optional[StarterRepo]` | Optional |

**Outputs:**

| State key | Type | Notes |
|---|---|---|
| `final_markdown` | `str` | Medium-formatted final draft with image/video URLs injected |
| `asset_bundle_url` | `str` | GCS URL of the bundle JSON |
| `memory_bank_recorded` | `bool` | True after the `covered` fact lands |
| `cycle_outcome` | `"published"` | Terminal state |

**Implementation (~70 lines):**

```python
# nodes/publisher.py
import json, logging, re
from datetime import datetime, timezone
from google.adk import Context, Event
from shared.memory import memory_bank_add_fact
from tools.gcs import upload_to_gcs
from tools.medium import medium_format

logger = logging.getLogger(__name__)

_IMG_MARKER_RE = re.compile(r"<!--IMG:(?P<pos>[^>]+?)-->")
_VID_MARKER_RE = re.compile(r"<!--VID:[^>]+?-->")

def publisher(node_input, ctx: Context) -> Event:
    chosen      = ctx.state["chosen_release"]
    draft       = ctx.state["draft"]
    images      = ctx.state.get("image_assets", [])
    video       = ctx.state.get("video_asset")
    repo        = ctx.state.get("starter_repo")
    cycle_id    = ctx.session.id[:8]

    # 1. Inject image URLs by position
    by_position = {img.position: img for img in images}
    def _img_replace(m: re.Match) -> str:
        pos = m.group("pos").strip()
        img = by_position.get(pos)
        if img is None:
            logger.warning("publisher: no image_asset for position %r", pos)
            return ""  # drop the broken marker rather than emit raw HTML
        return f"![{img.alt_text}]({img.url})"
    md = _IMG_MARKER_RE.sub(_img_replace, draft.markdown)

    # 2. Inject video (always at the marker if needs_video and video_asset both)
    if video is not None:
        # Single replacement — Architect mandates exactly one VID marker
        md = _VID_MARKER_RE.sub(
            f"![Demo]({video.gif_url})\n\n*Watch the [full video]({video.mp4_url}).*",
            md, count=1,
        )
    else:
        md = _VID_MARKER_RE.sub("", md)  # drop any stray VID markers

    # 3. Medium post-process
    final_md = medium_format(md)
    ctx.state["final_markdown"] = final_md

    # 4. Bundle to GCS
    bundle = {
        "title":           chosen["title"],
        "release_url":     chosen["url"],
        "release_source":  chosen["source"],
        "published_at":    datetime.now(timezone.utc).isoformat(),
        "markdown":        final_md,
        "image_assets":    [img.model_dump(mode="json") for img in images],
        "video_asset":     video.model_dump(mode="json") if video else None,
        "starter_repo":    repo.model_dump(mode="json") if repo else None,
    }
    bundle_bytes = json.dumps(bundle, indent=2).encode("utf-8")
    bundle_url = upload_to_gcs(
        payload=bundle_bytes,
        slug=f"{cycle_id}/article_bundle.json",
        content_type="application/json",
    )
    ctx.state["asset_bundle_url"] = bundle_url

    # 5. Memory Bank "covered" fact
    try:
        memory_bank_add_fact(
            scope="ai_release_pipeline",
            fact=f"Covered: {chosen['title']}",
            metadata={
                "type":           "covered",
                "release_url":    chosen["url"],
                "release_source": chosen["source"],
                "covered_at":     datetime.now(timezone.utc).isoformat(),
                "bundle_url":     bundle_url,
                "starter_repo":   repo.url if repo else None,
            },
        )
        ctx.state["memory_bank_recorded"] = True
    except Exception as e:
        logger.error("publisher: Memory Bank write failed: %s", e)
        ctx.state["memory_bank_recorded"] = False
        # Do NOT fail the cycle — the article is published; the dedup fact
        # being missing means we MAY re-cover the same release. Acceptable.

    ctx.state["cycle_outcome"] = "published"
    return Event(output={
        "outcome":     "published",
        "title":       chosen["title"],
        "bundle_url":  bundle_url,
        "memory_bank": ctx.state["memory_bank_recorded"],
    })
```

**Failure modes:**

| Failure | Recovery |
|---|---|
| Image marker references a position with no `image_asset` | Drop the marker (empty string); log warning. The article is otherwise complete. |
| `<!--VID:-->` marker present but `video_asset=None` | Drop the marker. |
| Multiple `<!--VID:-->` markers (Architect / Drafter mistake) | Replace only the first; subsequent ones get dropped. |
| `medium_format` raises | Cycle fails with a clear error; bundle is NOT written. (Acceptable — the Medium formatter is deterministic and well-tested; if it raises, something is genuinely broken.) |
| `upload_to_gcs` fails | Cycle fails. Bundle URL is required for downstream consumers. |
| Memory Bank write fails | Article IS published (state has `final_markdown` + `asset_bundle_url`); `memory_bank_recorded=False`. The next cycle MAY re-surface the same release; operator can skip via Topic Gate. |

**Tests:**

- *Image markers replaced by url-keyed positions* — feed draft + image_assets, assert each `<!--IMG:hero-->` becomes `![alt](url)`.
- *Missing image position drops the marker* — feed marker for "section_99" with no asset, assert empty replacement + warning logged.
- *Video marker becomes GIF + linked MP4 when video present* — assert resulting markdown contains both gif_url and mp4_url.
- *Video marker dropped when video_asset=None* — assert no `<!--VID:` survives.
- *Bundle JSON shape* — assert all fields present, image_assets is a list, video_asset is None or dict, repo is None or dict.
- *Memory Bank `covered` fact written with correct metadata* — mock memory bank, assert called with `type="covered"` + URL + source + bundle_url.
- *Memory Bank failure does NOT fail the cycle* — make memory bank raise; assert `cycle_outcome="published"` and `memory_bank_recorded=False`.
- *cycle_outcome set to "published"*.

### Decisions to challenge — chunk 4c §6.11

1. **Memory Bank `covered` fact failure does NOT fail the cycle.** The
   article is published successfully; the dedup fact missing means the
   release MIGHT be re-surfaced. Acceptable because operator has Topic
   Gate skip as a backstop. Push back if you want hard-fail.
2. **Bundle is a single JSON file in GCS** with markdown + asset URLs +
   metadata. Downstream consumers (Medium publisher, X cross-poster,
   etc.) read this single object. Push back if you want individual
   files (`article.md`, `bundle.json`) instead.
3. **Image positions that don't match a generated asset are dropped
   silently** (warning logged but no error). Alternative: render an
   inline error like `[image missing: hero]`. Defaulting to silent drop
   so the article still reads cleanly; the warning log surfaces in
   Cloud Logging for the operator.
4. **Publisher does NOT post anywhere outside GCS.** Per non-goal 4 in
   §2 — auto-publishing is out of v2 scope. The bundle URL is the
   handoff point.

---

### Summary table — chunks 4a + 4b + 4c (full §6 inventory)

| Chunk | § | Nodes | LLM agents | Function nodes |
|---|---|---|---|---|
| 4a | 6.1 | scout | 1 | 0 |
| 4a | 6.2 | triage, route_after_triage, record_triage_skip | 1 | 2 |
| 4a | 6.3 | topic_gate_request, record_topic_verdict, route_topic_verdict, record_human_topic_skip, record_topic_timeout | 0 | 5 |
| 4b | 6.4 | docs_researcher, github_researcher, context_researcher, gather_research | 3 | 1 |
| 4b | 6.5 | architect_llm, architect_split | 1 | 1 |
| 4b | 6.6 | drafter, critic_llm, critic_split, route_critic_verdict | 2 | 2 |
| 4c | 6.7 | image_asset_agent, video_asset_or_skip, gather_assets | 1 | 2 |
| 4c | 6.8 | route_needs_repo, repo_builder | 1 | 1 |
| 4c | 6.9 | editor_request, record_editor_verdict, route_editor_verdict, record_editor_rejection, record_editor_timeout | 0 | 5 |
| 4c | 6.10 | revision_writer | 1 | 0 |
| 4c | 6.11 | publisher | 0 | 1 |
| **Total** | | **28 nodes** | **11** | **17** |

§6 is now complete. Chunk 5 (§7 Tools) starts the next deep dive.

---

## §7 — Tools

§7 documents every Python module under `tools/` (and the new
`telegram_bridge/` separate service). Each tool entry has the same
shape:

- **Status** — `[port from v1]`, `[new for v2]`, or `[port + adapt]`
- **File** — where it lives in the v2 repo
- **Dependencies** — third-party packages required
- **Public API** — function signatures the rest of the code calls
- **Behavior** — what it does (in plain English; full code lives in the
  file)
- **Failure modes** — every bad outcome we've thought through
- **Tests** — the unit + smoke + live tests required

The 9 subsections are organized in dependency order — pollers first
(no dependencies on other tools), Telegram and Memory Bank middle (used
by both LLM agents and function nodes), GCS / Medium / Imagen / Veo /
GitHub later (used by asset/repo/publisher).

---

### §7.1 — Pollers (`tools/pollers.py`)

| Attribute | Value |
|---|---|
| **Status** | `[port from v1 — verbatim]` (already fixed during the recent poller work; live-tested 11/10 sources) |
| **File** | `tools/pollers.py` |
| **Dependencies** | `arxiv`, `feedparser`, `huggingface_hub`, stdlib `urllib`, `re`, `datetime` |

**Public API (7 polling functions + 4 helpers):**

```python
# Polling functions — each is wired as a Scout LlmAgent tool
def poll_arxiv(since: Union[datetime, str]) -> list[dict]: ...
def poll_github_trending(since: Union[datetime, str]) -> list[dict]: ...
def poll_rss(since: Union[datetime, str]) -> list[dict]: ...
def poll_hf_models(since: Union[datetime, str]) -> list[dict]: ...
def poll_hf_papers(since: Union[datetime, str]) -> list[dict]: ...
def poll_hackernews_ai(since: Union[datetime, str]) -> list[dict]: ...
def poll_anthropic_news(since: Union[datetime, str]) -> list[dict]: ...

# Helpers (private; module-internal)
def _ensure_utc(value: Optional[datetime]) -> Optional[datetime]: ...
def _parse_since(value: Union[datetime, str]) -> datetime: ...
def _parse_iso(value: Optional[str]) -> Optional[datetime]: ...
def _entry_published_at(entry) -> Optional[datetime]: ...

# Constants the Scout sees / tests assert against
RSS_FEEDS: dict[str, str] = {...}  # 8 lab feeds
ARXIV_QUERY = "cat:cs.AI OR cat:cs.LG OR cat:cs.CL"
ARXIV_MAX_RESULTS = 50
GITHUB_TRENDING_URL = "https://github.com/trending?since=daily&spoken_language_code=en"
HF_PAPERS_URL = "https://huggingface.co/api/daily_papers"
HN_AI_SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date?tags=story&query=AI&hitsPerPage=50"
ANTHROPIC_NEWS_URL = "https://www.anthropic.com/news"
HTTP_TIMEOUT_SECONDS = 10
USER_AGENT = "ai-release-pipeline-scout/0.2"  # bumped from /0.1 for v2
```

**What each poller returns.** Every poller returns `list[dict]` where
each dict is a `Candidate.model_dump(mode="json")` — `title`, `url`,
`source` (one of the SourceType Literal values), `published_at` (ISO
8601), `raw_summary`. **Empty list `[]` on any failure** (fail-open
contract that Scout depends on).

**Behavior summary (per source):**

| Poller | Source label | Method | Notes |
|---|---|---|---|
| `poll_arxiv` | `"arxiv"` | `arxiv` library, sorted by SubmittedDate desc | Filters by `since` cutoff in-process |
| `poll_github_trending` | `"github"` | HTML scrape of `/trending?since=daily` | `published_at = now()` (no per-entry dates); de-dup is Memory Bank's job |
| `poll_rss` | one of `{"google", "openai", "deepmind", "meta", "huggingface_blog", "nvidia", "microsoft", "bair"}` | `feedparser` against 8 URLs in `RSS_FEEDS` | Per-feed `try/except`; one bad feed doesn't break others |
| `poll_hf_models` | `"huggingface"` | `huggingface_hub.HfApi.list_models(sort="lastModified", limit=100)` | NO `direction=` kwarg (removed in `huggingface_hub>=0.25`) |
| `poll_hf_papers` | `"huggingface_papers"` | `GET /api/daily_papers` | The endpoint backing `huggingface.co/papers` |
| `poll_hackernews_ai` | `"hackernews"` | Algolia `/api/v1/search_by_date?tags=story&query=AI` | Newest-first; stops at `since` |
| `poll_anthropic_news` | `"anthropic"` | HTML scrape of `/news` index page | Anthropic has no RSS feed; humanizes URL slug → title |

**v2 changes vs v1 (none structural — just version bumps):**
- `USER_AGENT` bumps to `ai-release-pipeline-scout/0.2`.
- The `_parse_since` + `_parse_iso` helpers stay (already added during
  the recent poller fix work — handles ISO string from LlmAgent's JSON
  serialization).
- `SourceType` Literal in `shared/models.py` already extended to all
  16 values (chunks 4a/3 confirm).

**Failure modes (already documented in v1 work, repeated here for completeness):**

| Failure | Recovery |
|---|---|
| Single poller raises (timeout / parse error / API change) | `try/except` returns `[]`; logged via `logger.warning`. |
| All pollers return `[]` | Scout writes `candidates=[]`; Triage skips with `skip_reason="no candidates"` (§6.2). |
| LlmAgent passes `since` as ISO string instead of datetime | `_parse_since` accepts both. |
| HF `direction=-1` kwarg passed | Already removed in v1 fix. |
| Dead RSS URL | Not silently swallowed — an URL audit (`tests/smoke/pollers_smoke.py`) catches it; the `bozo` flag from feedparser surfaces. |

**Tests (carried over from v1 — already exist):**

| Test file | Coverage |
|---|---|
| `tests/test_scout.py` (25 tests) | Per-poller mocked tests + ISO-string regression + cap/dedupe |
| `tests/smoke/pollers_smoke.py` | Live-network smoke against real APIs; passes ≥10 sources (currently 11). Run via `PYTHONPATH=. uv run python tests/smoke/pollers_smoke.py`. |

**No new tests needed for v2 — the port is verbatim.**

---

### §7.2 — Memory Bank adapter (`tools/memory.py`)

| Attribute | Value |
|---|---|
| **Status** | `[new for v2]` (replaces v1's hand-rolled `shared/memory.py`) |
| **File** | `tools/memory.py` |
| **Dependencies** | `google-adk[memory]`, `google-cloud-aiplatform` |

**Why a thin adapter instead of using `VertexAiMemoryBankService`
directly?** Two reasons:
1. Triage and the recording nodes need a **simple two-function API**
   (`memory_bank_search`, `memory_bank_add_fact`) that matches v1's
   shape so prompts don't change.
2. **Local development + tests** need to swap in `InMemoryMemoryService`
   without touching agent/node code. A factory function in this module
   reads an env var and returns the right backend.

**Public API (the Triage / recording nodes call these):**

```python
# tools/memory.py

def memory_bank_search(query: str, scope: str = "ai_release_pipeline",
                       limit: int = 5) -> list[dict]:
    """Search Memory Bank for facts similar to ``query``.

    Returns a list of fact dicts; each has keys:
    ``fact`` (str), ``score`` (float, 0–1 similarity),
    ``metadata`` (dict — includes ``type``, ``release_url``, etc.).

    Returns ``[]`` on error (fail-open — Triage prefers false positives
    over false negatives).
    """
    ...

def memory_bank_add_fact(scope: str, fact: str, metadata: dict) -> bool:
    """Persist a fact to Memory Bank.

    ``metadata`` MUST include ``type`` ∈ {``"covered"``, ``"human-rejected"``}
    and ``release_url``, ``release_source``. Other metadata is free-form
    (the v2 publisher adds ``bundle_url``, ``starter_repo``).

    Returns True on success, False on error (caller may retry; recording
    nodes do not fail the cycle on Memory Bank errors per §6.3.2 / §6.11).
    """
    ...

# Internal — picks the backend based on env
def _get_memory_service():
    """Lazy-cached factory.

    Returns InMemoryMemoryService when MEMORY_BANK_BACKEND=inmemory.
    Returns VertexAiMemoryBankService(memory_bank_id=os.environ["MEMORY_BANK_ID"])
    otherwise (production default).
    """
    ...
```

**Backend selection (env vars):**

| Env var | Values | Effect |
|---|---|---|
| `MEMORY_BANK_BACKEND` | `inmemory` \| `vertex` (default `vertex`) | Picks the backend. Tests + local dev set `inmemory`. |
| `MEMORY_BANK_ID` | full resource path (`projects/.../locations/.../memoryBanks/...`) | Required for `vertex` backend |

**Behavior:**

1. **`memory_bank_search`**:
   - Calls `service.search_memory(query=query, app_name="ai_release_pipeline", filter={"scope": scope})`.
   - Maps results into the v2 dict shape (the managed service returns
     ADK `MemoryEntry` objects; we flatten to dicts so prompts don't
     need to know about ADK types).
   - Returns top `limit` results sorted by score desc.
   - Catches all exceptions, logs warning, returns `[]`.
2. **`memory_bank_add_fact`**:
   - Constructs an `Event` with the fact as content + metadata in the
     event actions.
   - Calls `service.add_session_to_memory(...)` with a synthetic single-event session.
   - Returns True on success, False on any error.

**Why a synthetic session for `add_fact`?** The managed Memory Bank
ingests session events, not raw facts. To "remember a fact" we
construct a one-event session whose user-content text IS the fact and
whose metadata holds the structured fields. Triage's `search_memory`
then surfaces it. (The `memory-bank` sample uses the same pattern.)

**Failure modes:**

| Failure | Recovery |
|---|---|
| Vertex Memory Bank returns 503 | `memory_bank_search` returns `[]`; Triage continues without dedup info (will likely re-cover a release; operator skips via Topic Gate). |
| Memory Bank quota exceeded | Same — return `[]`. |
| `MEMORY_BANK_ID` env var missing on the `vertex` backend | Module import-time error with a clear message: "set MEMORY_BANK_ID or MEMORY_BANK_BACKEND=inmemory." |
| `add_fact` partially succeeds (event written but metadata didn't persist) | Logged; returns True (caller treats as success — the fact IS searchable, just less detailed). |

**Tests:**

| Test | Backend | Asserts |
|---|---|---|
| `test_memory_search_returns_dict_shape` | inmemory | Output items have `fact`, `score`, `metadata` keys |
| `test_memory_add_fact_round_trip` | inmemory | Add a fact, search for it by title, assert it surfaces with score ≥ 0.7 |
| `test_memory_add_fact_metadata_required` | inmemory | Adding without `type` in metadata raises ValueError |
| `test_memory_search_returns_empty_on_service_error` | mocked service raising | `memory_bank_search` returns `[]`, warning logged |
| `test_factory_picks_inmemory_when_env_set` | env override | Asserts `_get_memory_service` returns `InMemoryMemoryService` |
| `test_factory_picks_vertex_when_env_unset` | env override | Asserts `VertexAiMemoryBankService` instantiation (mocked) |
| `test_memory_bank_smoke.py` (live) | vertex | Skipped without `MEMORY_BANK_ID`; full add+search round-trip against the real service. |

**Open question (chunk 6 / §15 Q2 will resolve):** Provisioning the
Memory Bank instance itself — Terraform `google_ai_memory_bank` resource
or `gcloud ai memory-banks create` + manual record of the `MEMORY_BANK_ID`?

---

### §7.3 — Telegram (`tools/telegram.py` + `telegram_bridge/`)

| Attribute | Value |
|---|---|
| **Status** | `[substantially new for v2]` (v1 had `tools/telegram_approval.py` doing long-poll; v2 splits into post + webhook bridge) |
| **Files** | `tools/telegram.py` (post helpers), `telegram_bridge/main.py` (Cloud Run service) |
| **Dependencies** | `python-telegram-bot` (post helpers); `fastapi`, `google-auth`, `requests` (bridge) |

This is two distinct surfaces:
- **Inside the workflow** — `tools/telegram.py` exports `post_topic_approval` and `post_editor_review`, called from `topic_gate_request` and `editor_request` (function nodes in §6.3.1 and §6.9.1). These are synchronous HTTP calls; they POST a Telegram message with inline-keyboard buttons.
- **Outside the workflow** — `telegram_bridge/` is a separate Cloud Run service. Telegram posts callback events to its `/telegram/webhook`. The bridge parses callback_data, looks up the (session_id, interrupt_id) mapping, and calls the AdkApp client to resume the paused workflow.

#### 7.3.1 — `tools/telegram.py` (post helpers)

**Public API:**

```python
# tools/telegram.py

def post_topic_approval(
    chosen: dict,
    session_id: str,
    interrupt_id: str,
) -> None:
    """Post the Topic Gate approval message with two buttons.

    Posts to TELEGRAM_APPROVAL_CHAT_ID. callback_data for each button is
    encoded as ``f"{session_id[:8]}|{choice}|{interrupt_id[:30]}"``.
    Choices: 'approve' | 'skip'.
    """
    ...

def post_editor_review(
    chosen: dict,
    draft_preview: str,
    image_urls: list[str],
    video_url: Optional[str],
    repo_url: Optional[str],
    session_id: str,
    interrupt_id: str,
) -> None:
    """Post the Editor review message with three buttons + ForceReply on Revise.

    Choices: 'approve' | 'reject' | 'revise'.
    On Revise, the operator's reply text is captured by the bridge as
    free-form feedback and packaged into the FunctionResponse payload.
    """
    ...

# Constants
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}"
HTTP_TIMEOUT_SECONDS = 10
```

**Behavior — `post_topic_approval`:**

1. Read `TELEGRAM_BOT_TOKEN` and `TELEGRAM_APPROVAL_CHAT_ID` from env.
2. Compose message text (HTML-escaped):
   ```
   <b>{chosen.title}</b>
   Source: {chosen.source} (score: {chosen.score})
   {chosen.url}
   <i>{chosen.rationale}</i>
   ```
3. Compose inline keyboard with two buttons (Approve / Skip), each with
   `callback_data = f"{session_id[:8]}|{choice}|{interrupt_id[:30]}"`.
4. POST to `https://api.telegram.org/bot{token}/sendMessage` with JSON
   body including `parse_mode="HTML"`, `reply_markup` containing the
   inline keyboard.
5. Raise on non-2xx (caller in `topic_gate_request` may retry — see §6.3.1
   failure modes; future enhancement: built-in retry with exponential
   backoff inside this helper).

**Behavior — `post_editor_review`:**

1. Same env reads as above.
2. Compose richer message text:
   ```
   <b>{chosen.title}</b> — Editor review
   Iteration: {iteration}
   Images: {len(image_urls)} ✓
   Video: {"✓ " + video_url if video_url else "—"}
   Repo: {"✓ " + repo_url if repo_url else "—"}
   
   <pre>{draft_preview[:500]}</pre>
   ```
3. Compose inline keyboard with three buttons:
   - Approve → `callback_data = "{prefix}|approve|{suffix}"`
   - Reject → `callback_data = "{prefix}|reject|{suffix}"`
   - Revise → `callback_data = "{prefix}|revise|{suffix}"`
4. POST. The Revise button has special handling on the bridge side: when
   tapped, the bridge sends a follow-up message with `force_reply: true`
   prompting the operator for free-text feedback.

**callback_data encoding contract** (referenced from §6.3.1, §6.9.1, and §8 chunk 6):

```
callback_data = f"{session_id[:8]}|{choice}|{interrupt_id[:30]}"
```

- 8-char session prefix
- pipe separator
- choice (≤7 chars: approve / skip / reject / revise)
- pipe separator
- 30-char interrupt_id prefix

Total: ≤8 + 1 + 7 + 1 + 30 = **47 bytes**, comfortably under the 64-byte
Telegram cap.

The bridge resolves the prefixes against a Firestore lookup keyed by
`{session_id_full → interrupt_id_full}`. See §7.3.2.

**Failure modes:**

| Failure | Recovery |
|---|---|
| `TELEGRAM_BOT_TOKEN` env unset | ImportError or RuntimeError at function call (clear message). |
| Network error / timeout | `requests.exceptions.RequestException` propagates; caller decides. The HITL function nodes wrap in their own `try/except` per §6.3.1 / §6.9.1. |
| Telegram returns 401 (invalid token) | Same — propagates; operator must rotate the secret. |
| Message exceeds 4096-char Telegram cap | `post_editor_review` truncates `draft_preview` to 500 chars (other fields are short); the cap should never be hit. Defensive truncation if computed total > 4000. |

**Tests:**

| Test | Asserts |
|---|---|
| `test_post_topic_approval_calls_telegram_with_two_buttons` | Mock requests, assert called once with sendMessage and 2-button keyboard |
| `test_post_topic_approval_callback_data_under_64_bytes` | For long URLs, assert each button's callback_data is ≤64 bytes |
| `test_post_editor_review_three_buttons` | Mock requests, assert 3-button keyboard |
| `test_post_editor_review_omits_video_line_when_none` | Message text doesn't have "Video:" line when video_url is None |
| `test_post_telegram_smoke.py` (live) | Sends a real message to TELEGRAM_APPROVAL_CHAT_ID; skipped without env. |

#### 7.3.2 — `telegram_bridge/` (Cloud Run service)

| Attribute | Value |
|---|---|
| **File** | `telegram_bridge/main.py` (FastAPI app), `telegram_bridge/Dockerfile`, `telegram_bridge/requirements.txt` |
| **Cloud Run service name** | `ai-release-pipeline-v2-telegram` |
| **Min instances** | 0 (cold start ~3s; acceptable for click latency) |
| **Identity** | Dedicated SA `airel-v2-telegram-bridge@<project>.iam.gserviceaccount.com` with `roles/aiplatform.user` (to call AdkApp) and `roles/datastore.user` (Firestore access) |

**Endpoints:**

```python
# telegram_bridge/main.py

@app.post("/telegram/webhook")
def webhook(update: TelegramUpdate, x_telegram_bot_api_secret_token: str = Header(...)) -> dict:
    """Receive a Telegram callback_query OR a force-reply message.

    1. Verify x_telegram_bot_api_secret_token matches TELEGRAM_WEBHOOK_SECRET.
    2. If update is a callback_query:
       - Parse callback_data → (session_pref, choice, interrupt_pref)
       - Look up full IDs in Firestore (collection: airel_v2_sessions,
         doc id: session_pref)
       - For 'revise', send a force_reply prompt and stash the
         interrupt_id in pending state (a separate Firestore doc) — wait
         for the next /webhook call carrying the reply text.
       - For 'approve' / 'skip' / 'reject', call resume_session() with
         the choice.
    3. If update is a message replying to a 'revise' force_reply:
       - Look up the pending interrupt_id by reply_to_message_id.
       - Call resume_session(decision='revise', feedback=<message text>).

    Returns {"ok": true}. Telegram retries on non-200.
    """

def resume_session(session_id: str, interrupt_id: str, decision: str,
                   feedback: Optional[str] = None) -> None:
    """Mint OIDC ID token for the AdkApp client; POST FunctionResponse.

    Uses the AdkApp client (`vertexai.preview.reasoning_engines.AdkApp`)
    to send a Content with a Part containing FunctionResponse keyed by
    interrupt_id. The workflow resumes from its paused HITL node.
    """
```

**Why Firestore for the (prefix → full ID) lookup?** Two reasons:
1. The bridge MAY scale to multiple instances (cold start avoidance); a
   shared store is required.
2. The data is tiny (one doc per active paused session, deleted on
   resume) — Firestore's free tier covers it indefinitely.

Alternative considered: in-memory KV with `min_instances=1` to pin to
one instance. Rejected — single-instance is fragile; Firestore is one
extra dependency that buys correctness.

**`Firestore` schema (one collection):**

```
collection: airel_v2_sessions
doc id:     {session_id_short_prefix}     # 8 chars
fields:
  session_id_full:     str
  interrupt_id_full:   str
  created_at:          timestamp
  expires_at:          timestamp           # session_id TTL = 7 days
  pending_revise_id:   str | null          # set when bridge sent ForceReply
```

A separate Cloud Scheduler job (`airel-v2-cleanup`, daily) deletes
expired docs.

**Behavior — `resume_session`:**

```python
# telegram_bridge/main.py (continued)
import google.auth
from google.auth.transport.requests import Request
from google.oauth2 import id_token
import requests
import os

def resume_session(session_id, interrupt_id, decision, feedback=None):
    # Construct the FunctionResponse payload (see spike test #2)
    function_response = {
        "id":   interrupt_id,
        "name": _function_name_for_interrupt(interrupt_id),  # "topic_gate_request" | "editor_request"
        "response": {"decision": decision, **({"feedback": feedback} if feedback else {})},
    }
    body = {
        "class_method": "stream_query",
        "input": {
            "user_id": "telegram-bridge",
            "session_id": session_id,
            "message": {
                "role": "user",
                "parts": [{"function_response": function_response}],
            },
        },
    }
    target = f"{os.environ['AGENT_RUNTIME_ENDPOINT']}:streamQuery?alt=sse"
    auth_req = Request()
    token = id_token.fetch_id_token(auth_req, target)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    resp = requests.post(target, json=body, headers=headers, stream=True, timeout=15)
    resp.raise_for_status()
    # Drain a few SSE events to confirm resume started; then exit.
    for i, line in enumerate(resp.iter_lines()):
        if line and line.startswith(b"data: "):
            logger.info("resumed event %d", i)
        if i >= 3:
            break
```

**Why does `resume_session` only drain 3 events?** Same reason the v1
Cloud Function did — once the workflow has accepted the resume, it
runs detached on Agent Runtime. The bridge doesn't need to hold the
connection open.

**Failure modes:**

| Failure | Recovery |
|---|---|
| Missing / invalid `x_telegram_bot_api_secret_token` | Return 403; do NOT log the token (it would land in Cloud Logging). |
| Firestore lookup miss (session expired or never written) | Return 200 with `{"ok": false, "reason": "session not found"}`; tell Telegram NOT to retry (HTTP 200). Send a follow-up Telegram message to the operator: "This approval is no longer valid (session expired)." |
| Agent Runtime returns 401 (auth misconfigured) | Return 500; Telegram retries (Telegram retries non-200 webhooks for ~24h). Operator should see logs. |
| Agent Runtime returns 4xx for malformed FunctionResponse | Return 500; logs include the failing payload. Bug-hunt. |
| Operator taps a button twice (network glitch on first reply) | Second tap: Firestore lookup succeeds, resume_session is called again → Agent Runtime sees a duplicate function_response. We rely on Agent Runtime's idempotency for the same interrupt_id. (Need to verify this — see §15 Q4.) |

**Tests:**

| Test | Asserts |
|---|---|
| `test_webhook_rejects_missing_secret_header` | 403 returned |
| `test_webhook_parses_callback_data` | Three-tuple extraction correct |
| `test_webhook_resolves_full_ids_from_firestore` | Mock Firestore, assert lookup with the short prefix |
| `test_revise_button_sends_force_reply` | Mock bot.sendMessage, assert force_reply: true |
| `test_resume_session_constructs_FunctionResponse` | Mock requests, assert POSTed body has `function_response.id == interrupt_id` |
| `test_expired_session_returns_user_friendly_error` | Firestore mock returns None, assert 200 with reason and follow-up message sent |
| Live integration | Run the bridge locally with ngrok; tap a real button; assert the workflow resumes |

#### Decisions to challenge — chunk 5 §7.3

1. **Bridge uses Firestore for short-prefix → full-ID lookup.** Adds
   a service dependency. Alternative: encode the FULL session_id in
   callback_data using base32 (24 chars), keep `interrupt_id` short.
   Trade: slightly more brittle if `interrupt_id` ever needs to grow.
2. **`force_reply` handling for Revise lives in the bridge**, not in
   the workflow. The workflow sees one resume call with both `decision`
   and `feedback`. Cleaner. Push back if you'd rather have two pause
   points (one for the choice, one for the feedback).
3. **`resume_session` calls Agent Runtime via `:streamQuery?alt=sse`** —
   the documented HTTP API. Alternative: import `vertexai.preview.reasoning_engines.AdkApp` client SDK. Picked HTTP for fewer deps in the bridge container. Push back if you want the SDK.
4. **Bridge cold-start latency is acceptable** (~3s for the operator to
   see the workflow advance after a button tap). If unacceptable, set
   `min_instances=1` (cost: $5–10/month).

---

### §7.4 — Web fetch (`tools/web.py`)

| Attribute | Value |
|---|---|
| **Status** | `[port from v1 — verbatim]` |
| **File** | `tools/web.py` |
| **Dependencies** | stdlib `urllib.request` only — no third-party HTTP client |

**Public API:**

```python
def web_fetch(url: str) -> str:
    """Fetch URL and return decoded text (truncated to 200KB).

    Used by docs_researcher and context_researcher (LlmAgent tools).
    Returns ``""`` on any error (fail-safe — researchers degrade
    gracefully).
    """
```

**Behavior:** stdlib `urllib.request.urlopen` with `User-Agent`
header, 10s timeout, 200KB read cap, UTF-8 decode with `errors="replace"`.

**Failure modes:** Catches all exceptions, returns `""`, logs warning.

**Tests:** Already exist in v1 (`tests/test_researchers.py`). Carry over.

---

### §7.5 — GitHub ops (`tools/github_ops.py`)

| Attribute | Value |
|---|---|
| **Status** | `[port from v1 — verbatim]` (already audited in v1 audit row B12 as PASS) |
| **File** | `tools/github_ops.py` |
| **Dependencies** | `PyGithub` |

**Public API (6 functions — 3 read, 3 write):**

```python
# Read — used by github_researcher
def github_get_repo(repo_full_name: str) -> dict: ...
def github_get_readme(repo_full_name: str, ref: str = "HEAD") -> str: ...
def github_list_files(repo_full_name: str, ref: str = "HEAD",
                      max_entries: int = 50) -> list[str]: ...

# Write — used by repo_builder
def github_create_repo(name: str, description: str = "",
                       private: bool = False, org: Optional[str] = None) -> dict: ...
def github_commit_files(repo: str, files: list[tuple[str, Union[str, bytes]]],
                        message: str, branch: str = "main",
                        source_url: Optional[str] = None) -> dict: ...
def github_set_topics(repo: str, topics: list[str]) -> dict: ...
```

**Atomic multi-file commits** — `github_commit_files` uses the Git Data
API (`create_git_blob` + `create_git_tree` + `create_git_commit` + ref
update). Either every file in the SHA or none. Supports binary blobs
via `source_url` (fetches the URL bytes, base64-encodes for the blob).

**Auth:** `GITHUB_TOKEN` env (Personal Access Token with `repo` scope
for create/commit; `delete_repo` is NOT used by repo_builder so the
token does not need that scope).

**Failure modes:** Each function returns `{"error": "..."}` on failure
rather than raising — repo_builder LlmAgent reads the dict and acts
accordingly.

**Tests:** Already in v1 (`tests/test_repo_builder.py` + `tests/smoke/github_smoke.py`). Carry over verbatim.

---

### §7.6 — Imagen (`tools/imagen.py`)

| Attribute | Value |
|---|---|
| **Status** | `[port from v1 — model name fixed]` |
| **File** | `tools/imagen.py` |
| **Dependencies** | `google-genai`, `google-cloud-aiplatform` |

**Public API:**

```python
def generate_image(
    prompt: str,
    aspect_ratio: AspectRatio = "16:9",
    style: ImageStyle = "illustration",
) -> bytes:
    """Generate one image via Vertex Imagen; return raw PNG bytes.

    Default model: ``imagen-4.0-fast-generate-001`` (was ``-preview`` in
    v1; that 404'd in production — Bug B4).
    Override via ``NANO_BANANA_MODEL`` env var.
    """
```

**Behavior:**
- `client = genai.Client(vertexai=True, project=..., location=...)`
- `client.models.generate_images(model=NANO_BANANA_MODEL, prompt=..., config={"aspectRatio": ..., "numberOfImages": 1})`
- Returns `result.images[0].image.image_bytes`.

**Style hint composition** — the LlmAgent (image_asset_agent) does
high-level prompt augmentation; this function appends a one-line style
modifier to the prompt:

```python
_STYLE_HINTS = {
    "photoreal":    "photorealistic, high detail",
    "diagram":      "clean technical diagram, minimal style",
    "illustration": "modern editorial illustration, flat colors",
    "screenshot":   "realistic UI screenshot, dark mode",
}
```

**Failure modes:**

| Failure | Recovery |
|---|---|
| Model 404 (wrong ID) | `genai.errors.ClientError` propagates; image_asset_agent's tool wrapper catches and returns placeholder. |
| Quota exceeded | Same — caller treats as a per-brief failure (placeholder), not a cycle abort. |
| Safety filter blocks | API returns no images; function raises `ValueError("Imagen returned 0 images")`; caller treats as placeholder. |

**Tests:** Carry from v1 (`tests/test_assets.py`). Add one new test:
*`test_generate_image_default_model_is_001_not_preview`* — assert the
default constant is `imagen-4.0-fast-generate-001`.

---

### §7.7 — Veo + video processing (`tools/veo.py`, `tools/video_processing.py`)

| Attribute | Value |
|---|---|
| **Status** | `[port from v1 — model name pending §15 Q6]` |
| **Files** | `tools/veo.py`, `tools/video_processing.py` |
| **Dependencies** | `google-genai`, `ffmpeg-python` (which requires ffmpeg system binary in the container) |

**Public API:**

```python
# tools/veo.py
def generate_video(
    prompt: str,
    duration_seconds: int,
    aspect_ratio: AspectRatio = "16:9",
) -> bytes:
    """Generate a short video via Vertex Veo; return raw MP4 bytes.

    duration_seconds is clamped to [1, 8] in body (defense against
    LLM-supplied bad values).
    Default model: env VEO_MODEL — TBD per §15 Q6 (v1 default
    'veo-3.1-fast-generate-preview' was wrong / 404'd in production).
    """

MAX_DURATION_SECONDS = 8

# tools/video_processing.py
def convert_to_gif(mp4_bytes: bytes) -> bytes:
    """ffmpeg: 10fps, 720px max width, palettegen filter."""

def extract_first_frame(mp4_bytes: bytes) -> bytes:
    """ffmpeg: -frames:v 1 -c:v mjpeg."""
```

**Why a separate `video_processing.py`?** Single-responsibility — Veo is
a network call; ffmpeg work is local subprocess. Failure modes differ.

**Failure modes:**

| Failure | Recovery |
|---|---|
| Veo model 404 | Caller (`video_asset_or_skip` function node) catches, sets `video_asset=None`, continues. |
| Veo quota exceeded | Same. |
| Veo long-running operation timeout | Same. |
| ffmpeg binary not in container | Container build fails; runs CI catches via `apt-get install -y ffmpeg` in Dockerfile. (Wait — Agent Runtime is source-based, no Dockerfile. The Veo path may need a custom container image. **§15 Q8 added below.**) |
| ffmpeg subprocess error | Caller catches, `video_asset=None`. |

**Tests:** Carry from v1 (`tests/test_assets.py` for Veo wiring; live
test gated on `--include-veo` flag because Veo is paid). Add:
*`test_max_duration_clamped`* — feed `duration=20`, assert it's clamped
to 8 in the API call.

**§15 Q8 (added by chunk 5):** Agent Runtime is source-based, no
Dockerfile. How do we install the ffmpeg system binary? Options:
1. Pure-Python video lib (e.g., `imageio-ffmpeg` ships ffmpeg binary in the wheel — large dep but no system install).
2. Custom Veo path that calls Vertex's GIF + thumbnail extraction (if Vertex offers it server-side).
3. Move video processing to a separate Cloud Run service that the
   workflow calls as a tool (extra hop, extra cost).
4. Accept that v2 ships WITHOUT GIF + poster (only MP4); skip
   `convert_to_gif` and `extract_first_frame`. **Simplest** —
   `needs_video=true` stays rare anyway.

**Default in this draft: option 4.** v2 ships with MP4 only. The Editor
preview shows the MP4 URL; Publisher injects the MP4 as a video tag,
not a GIF. Push back if any downstream consumer specifically needs the
GIF + poster.

---

### §7.8 — GCS upload (`tools/gcs.py`)

| Attribute | Value |
|---|---|
| **Status** | `[port from v1 — verbatim]` |
| **File** | `tools/gcs.py` |
| **Dependencies** | `google-cloud-storage` |

**Public API:**

```python
def upload_to_gcs(
    payload: bytes,
    slug: str,
    content_type: str = "application/octet-stream",
) -> str:
    """Upload bytes to GCS_ASSETS_BUCKET; return public HTTPS URL.

    Bucket from env GCS_ASSETS_BUCKET (v2 default:
    gen-lang-client-0366435980-airel-assets-v2 — fresh bucket per §3).
    Returns f"https://storage.googleapis.com/{bucket}/{slug}".
    """
```

**Behavior:** `google.cloud.storage.Client()` → `bucket.blob(slug).upload_from_string(payload, content_type=content_type)`. Bucket has uniform IAM with `allUsers:objectViewer` per §3.

**Failure modes:** Raises `google.api_core.exceptions.GoogleAPIError`
on any failure. Callers (Imagen / Veo / Publisher) handle.

**Tests:** Carry from v1 (`tests/test_assets.py`). Add:
*`test_upload_uses_v2_default_bucket`* — assert default env value points
at `*-airel-assets-v2`.

---

### §7.9 — Medium formatter (`tools/medium.py`)

| Attribute | Value |
|---|---|
| **Status** | `[port from v1 — verbatim]` |
| **File** | `tools/medium.py` |
| **Dependencies** | stdlib `re` only |

**Public API:**

```python
def medium_format(markdown: str) -> str:
    """Apply Medium-publication-friendly normalization.

    1. Demote any extra H1 (#) to H2 (##) — Medium uses one H1 per article.
    2. Add `python` language hint to fenced code blocks that lack a
       language tag (Medium renders unhinted code as monospace prose).
    3. Collapse 3+ consecutive blank lines to 2.
    4. Ensure article ends with a single trailing newline.
    """
```

**Failure modes:** None — pure string transformation; no I/O.

**Tests:** Carry from v1. Add fixtures for the three transformations.

---

### Tool-to-node call graph (sanity check)

| Tool | Called by |
|---|---|
| `poll_*` (7) | `scout` only |
| `memory_bank_search` | `triage` only |
| `memory_bank_add_fact` | `record_topic_verdict`, `publisher` |
| `post_topic_approval` | `topic_gate_request` only |
| `post_editor_review` | `editor_request` only |
| `web_fetch` | `docs_researcher`, `context_researcher` |
| `google_search` (built-in ADK) | `docs_researcher`, `context_researcher` |
| `github_get_repo` / `_get_readme` / `_list_files` | `github_researcher` only |
| `github_create_repo` / `_commit_files` / `_set_topics` | `repo_builder` only |
| `generate_image` | `image_asset_agent` only |
| `upload_to_gcs` | `image_asset_agent`, `video_asset_or_skip`, `publisher` |
| `generate_video` | `video_asset_or_skip` only |
| `convert_to_gif` / `extract_first_frame` | `video_asset_or_skip` (deferred per §7.7 Q8 — option 4 ships MP4-only) |
| `medium_format` | `publisher` only |

The graph is a DAG with no orphan tools and no node calling the same
tool from two different code paths (clean ownership). 

### Decisions to challenge — chunk 5 (cross-cutting)

1. **`tools/memory.py` is a thin adapter** that picks backend via env
   var (`vertex` vs `inmemory`). Tests run on `inmemory`; production
   on `vertex`. Push back if you want both backends in production
   (e.g. `inmemory` as fast-path local cache + `vertex` as durable).
2. **Telegram bridge is its own Cloud Run service** with its own
   service account, Firestore lookup, and Dockerfile. Adds a moving
   part. Alternative: bundle the bridge inside the Agent Runtime
   service. Rejected because Agent Runtime doesn't expose arbitrary
   HTTP endpoints; we'd need a custom server. Cloud Run is simpler.
3. **Video pipeline ships MP4-only in v2** (no GIF + poster). §7.7 Q8.
   Operator can request the GIF derivation as a v2.1 enhancement.
4. **`USER_AGENT` bumps to `/0.2`** for v2. Lets API providers see the
   version we're running — useful for debugging if they introduce
   server-side rate limits per UA.
5. **No `.env`-based secrets in any tool module.** All secrets are
   injected as env vars by the Agent Runtime / Cloud Run deployment
   (sourced from Secret Manager). Tools must NEVER read `.env`
   directly — that breaks deployment isolation.

---

## §8 — HITL contract

§8 is normative reference for the human-in-the-loop mechanic that
appears at two points in the workflow (Topic Gate in §6.3 and Editor in
§6.9). Every implementation that touches `RequestInput`, Telegram
buttons, or session resume MUST cite this section.

The contract has four layers:

```
                ┌──────────────────────────┐
                │ §8.1 RequestInput shape  │  ← what the workflow yields
                └────────────┬─────────────┘
                             │
                             ▼
                ┌──────────────────────────┐
                │ §8.2 Telegram callback   │  ← what the bridge encodes
                │      data encoding       │     into button payloads
                └────────────┬─────────────┘
                             │
                             ▼
                ┌──────────────────────────┐
                │ §8.3 Resume protocol     │  ← what the bridge sends
                │      (FunctionResponse)  │     back to Agent Runtime
                └────────────┬─────────────┘
                             │
                             ▼
                ┌──────────────────────────┐
                │ §8.4 Timeout & escalation│  ← who/how cancels stuck pauses
                └──────────────────────────┘
```

### §8.1 — `RequestInput` shape

The workflow pauses when a function node yields a
`google.adk.events.RequestInput` event. Spike test #2 confirmed the
mechanic; this section pins down the conventions for each field.

**Field reference:**

| Field | Type | Required | Convention |
|---|---|---|---|
| `interrupt_id` | `str` | Yes | Stable, recoverable string keyed to (node, release, iteration). Format below. |
| `payload` | `Optional[Any]` | Yes (we always set it) | The data the bridge / human needs to make the decision. For Topic Gate: the full `chosen_release` dict. For Editor: a thin dict (no full draft — the operator already has the Telegram preview). |
| `message` | `Optional[str]` | Yes (we always set it) | A human-readable string that lands in Cloud Trace and Cloud Logging. NOT the message Telegram displays — that comes from `tools/telegram.py:post_*`. |
| `response_schema` | `Optional[SchemaType]` | No | A Pydantic model the runtime validates the resume payload against. We do NOT use this in v2 — `record_*_verdict` nodes do their own coercion (`_coerce_decision`, `_coerce_editor_response`). |

**`interrupt_id` format — node-specific conventions:**

| Node | Format | Why |
|---|---|---|
| `topic_gate_request` | `f"topic-gate-{short_hash(chosen_release.url)}"` | Stable across retries. Duplicate Pub/Sub triggers on the same URL deliberately collide → second trigger joins the first paused session (Goal 4 idempotency in §2). |
| `editor_request` | `f"editor-{session_id[:8]}-{editor_iterations}"` | Iteration-suffixed because revision loops produce multiple pauses on the same session. Bridge MUST disambiguate "approve revision 1" from "approve revision 2." |

**`short_hash(url)` definition:**

```python
import hashlib
def short_hash(url: str, length: int = 12) -> str:
    """SHA-256, base32-encoded, lowercased, truncated. Collision-safe at our volume."""
    digest = hashlib.sha256(url.encode("utf-8")).digest()
    import base64
    return base64.b32encode(digest).decode("ascii").lower()[:length]
```

12-char base32 = 60 bits of entropy; collision probability at <1000
releases/year is effectively zero. Lowercase because callback_data is
case-sensitive and we want grep-friendly logs.

**`payload` shape — node-specific:**

| Node | Payload contract |
|---|---|
| `topic_gate_request` | `chosen_release.model_dump(mode="json")` — the full ChosenRelease dict |
| `editor_request` | `{"draft_iteration": draft.iteration, "editor_iterations": editor_iterations}` — minimal; the operator's Telegram preview already shows the draft |

**`message` shape — node-specific:**

| Node | Message template |
|---|---|
| `topic_gate_request` | `f"Topic Gate: approve {chosen.title!r}? (score={chosen.score}, source={chosen.source})"` |
| `editor_request` | `f"Editor: {chosen.title!r} — approve, revise, or reject?"` |

These show up in trace spans, not Telegram. Telegram message text comes
from `tools/telegram.py`.

**Tests:**

- *interrupt_id is stable across calls with same chosen_release.url* — important for idempotency.
- *editor_request interrupt_id changes between iterations* — assert iter 0 vs iter 1 produce different IDs.
- *payload is JSON-serializable* — round-trip through `json.dumps` / `loads`.

### §8.2 — Telegram `callback_data` encoding

Telegram button taps echo the `callback_data` string back to the
webhook. Telegram caps `callback_data` at **64 bytes**. We encode three
identifiers into that budget so the bridge can resolve the resume
target without keeping all of state in callback_data.

**Format:**

```
{session_prefix}|{choice}|{interrupt_prefix}
        ^           ^             ^
   8 chars     ≤7 chars     ≤30 chars
       │           │             │
       │           │             └─── short prefix of interrupt_id
       │           └─── one of: approve / skip / reject / revise
       └─── first 8 chars of session_id (a UUID, so >40 bits of entropy)
```

**Byte budget table:**

| Component | Bytes | Notes |
|---|---|---|
| `session_prefix` | 8 | First 8 chars of UUID4 — collision risk negligible per cycle |
| separator `\|` | 1 | |
| `choice` | up to 7 | Longest is `approve` |
| separator `\|` | 1 | |
| `interrupt_prefix` | up to 30 | First 30 chars of `interrupt_id` (Topic Gate IDs are ~24 chars total; Editor IDs are ~22) |
| **Total** | **≤47** | Comfortably under Telegram's 64-byte cap |

**Bridge resolution (§7.3.2 spec, restated here):**

The bridge maintains a Firestore collection
`airel_v2_sessions` keyed by `session_prefix`. Each doc carries the
full IDs:

```
{
  "session_id_full":   "<full UUID>",
  "interrupt_id_full": "<full interrupt_id>",
  "created_at":        <timestamp>,
  "expires_at":        <created_at + 7 days>,
  "pending_revise_id": null  // set when bridge sent ForceReply for this session
}
```

The HITL function nodes are responsible for writing this doc
**before** posting to Telegram (so the bridge always has the lookup
ready). `tools/telegram.py:post_topic_approval` and `:post_editor_review`
do the Firestore write inline.

**Bridge resolution algorithm (pseudocode):**

```python
def resolve(callback_data: str) -> tuple[str, str, str]:
    sess_pref, choice, interrupt_pref = callback_data.split("|", 2)
    doc = firestore.collection("airel_v2_sessions").document(sess_pref).get()
    if not doc.exists:
        raise SessionExpired(f"no session for prefix {sess_pref}")
    full_session_id   = doc["session_id_full"]
    full_interrupt_id = doc["interrupt_id_full"]
    if not full_interrupt_id.startswith(interrupt_pref):
        raise PrefixMismatch(f"interrupt prefix {interrupt_pref} != {full_interrupt_id[:30]}")
    return full_session_id, full_interrupt_id, choice
```

**Why a prefix match check (not equality)?** Defense in depth — if a
session ever has multiple interrupt_ids in flight (it shouldn't, but),
the prefix mismatch surfaces it loudly before the bridge resumes the
wrong pause.

**Encoding tests:**

- *encoded_callback_data_is_at_most_47_bytes_for_worst_case_url* — feed a 200-char URL, assert resulting callback_data ≤47 bytes.
- *roundtrip_callback_data* — encode then `parse`, assert all three components recovered.
- *session_prefix_collision_at_8_chars* — generate 1000 random UUIDs, assert no two share an 8-char prefix (probabilistic; loose tolerance).

### §8.3 — Resume protocol (FunctionResponse `Part`)

The bridge resumes a paused workflow by POSTing a `Content` message to
the Agent Runtime trigger endpoint where one `Part` is a
`FunctionResponse` keyed by the matching `interrupt_id`. Spike test #2
nailed the exact shape; here is the canonical reference.

**`Content` shape the bridge sends:**

```python
from google.genai import types as genai_types

content = genai_types.Content(
    role="user",
    parts=[
        genai_types.Part(
            function_response=genai_types.FunctionResponse(
                id=full_interrupt_id,         # MUST equal the RequestInput.interrupt_id
                name=function_name,           # node function name (see table below)
                response={"decision": choice, **maybe_feedback},
            ),
        ),
    ],
)
```

**Why MUST the `id` equal the `interrupt_id`?** Because ADK 2.0's
runner matches the function call (the `RequestInput`-yielding node)
against this response by `id`. Wrong ID = the runtime treats this as a
NEW user message instead of a resume → workflow restarts from scratch.
Spike test #2 surfaced this explicitly.

**`name` — must equal the yielding node's function name:**

| Node | `function_response.name` |
|---|---|
| `topic_gate_request` | `"topic_gate_request"` |
| `editor_request` | `"editor_request"` |

(The bridge can derive this from a string prefix on `interrupt_id` —
see `_function_name_for_interrupt` in §7.3.2:

```python
def _function_name_for_interrupt(iid: str) -> str:
    if iid.startswith("topic-gate-"): return "topic_gate_request"
    if iid.startswith("editor-"):     return "editor_request"
    raise ValueError(f"unknown interrupt_id prefix: {iid}")
```

Adding a new HITL node = add one line here.)

**`response.decision` — node-specific allowed values:**

| Node | Allowed `decision` values |
|---|---|
| `topic_gate_request` | `"approve"` \| `"skip"` \| `"timeout"` |
| `editor_request` | `"approve"` \| `"reject"` \| `"revise"` \| `"timeout"` |

**`response.feedback` — present only when `decision == "revise"`:**

```json
{"decision": "revise", "feedback": "Make the intro shorter."}
```

For all other decisions, the field is omitted. `record_editor_verdict`
treats a missing `feedback` on a `revise` response as empty-string and
applies a default rewrite instruction (§6.10).

**Worked example — bridge resumes Editor with revise + feedback:**

```python
content = genai_types.Content(
    role="user",
    parts=[
        genai_types.Part(
            function_response=genai_types.FunctionResponse(
                id="editor-1f29cf7e-0",  # interrupt_id of the paused editor_request
                name="editor_request",
                response={
                    "decision": "revise",
                    "feedback": "Add a short comparison vs LangChain Agents in §3.",
                },
            ),
        ),
    ],
)
# Bridge POSTs this as the new_message in :streamQuery?alt=sse
```

**Tests:**

- *function_response_id_matches_interrupt_id* — bridge unit test.
- *function_response_name_resolves_from_interrupt_prefix* — `_function_name_for_interrupt` is total over the two prefixes; raises on unknown.
- *resume_with_wrong_id_starts_new_invocation* — integration test (against InMemoryRunner) confirming the contract: setting `id` to a random string causes the workflow to restart instead of resume. (This test EXISTS to document the failure mode and prevent silent regressions.)

### §8.4 — Timeout & escalation

**ADK 2.0 `RequestInput` has NO built-in timeout.** A paused workflow
stays paused indefinitely until either (a) a resume call arrives or
(b) the session is explicitly deleted. This is by design — Agent
Runtime doesn't want to silently fail on long-running human
interactions. We bring our own timeout.

**Mechanism — a separate Cloud Scheduler "sweeper":**

```
┌────────────────────────────────────────────────────────────────────┐
│  Cloud Scheduler: airel-v2-hitl-sweeper                            │
│  schedule: */15 * * * *  (every 15 min)                            │
│  target: HTTP POST → telegram_bridge /sweeper/escalate             │
└─────────────────────────────────┬──────────────────────────────────┘
                                  │
                                  ▼
┌────────────────────────────────────────────────────────────────────┐
│  telegram_bridge: POST /sweeper/escalate                           │
│   1. Query Firestore: docs where created_at < now - 24h            │
│      AND no termination ack                                        │
│   2. For each stale doc:                                           │
│      - call resume_session(decision="timeout")                     │
│      - mark Firestore doc as terminated                            │
└────────────────────────────────────────────────────────────────────┘
```

**Why 15-minute cadence and 24h timeout?** 24h is the design's
operator SLA from v1 (§2 Goal 2). 15-minute cadence means a stuck
session is escalated within 15 min of crossing the 24h mark — fine
granularity without spamming Cloud Scheduler.

**Why call `resume_session(decision="timeout")` instead of deleting the
session?** Two reasons:
1. The workflow's terminal nodes (`record_topic_timeout`,
   `record_editor_timeout`) need to run so `cycle_outcome` is set.
   Deleting the session skips these.
2. Cloud Trace gets a clean trace ending instead of an abandoned span.

**Per-node timeout behavior:**

| Node | Timeout outcome | Memory Bank fact written? |
|---|---|---|
| `topic_gate_request` | `record_topic_timeout` runs → `cycle_outcome="topic_timeout"` | NO — release stays surface-able (§6.3.5) |
| `editor_request` | `record_editor_timeout` runs → `cycle_outcome="editor_timeout"` | NO — same logic (§6.9.5) |

**Sweeper algorithm:**

```python
# telegram_bridge/main.py — sweeper endpoint
@app.post("/sweeper/escalate")
def escalate_stale_pauses() -> dict:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    stale_docs = (
        firestore.collection("airel_v2_sessions")
        .where(filter=FieldFilter("created_at", "<", cutoff))
        .where(filter=FieldFilter("terminated", "==", False))
        .stream()
    )
    timed_out = 0
    for doc in stale_docs:
        data = doc.to_dict()
        try:
            resume_session(
                session_id=data["session_id_full"],
                interrupt_id=data["interrupt_id_full"],
                decision="timeout",
            )
            doc.reference.update({"terminated": True})
            timed_out += 1
        except Exception as e:
            logger.error("sweeper failed for %s: %s", data["session_id_full"], e)
    return {"timed_out": timed_out}
```

**Escalation NOT covered in v2** (deferred to v3):
- Auto-DM the operator at 12h ("approval pending for 12h, will time out
  in 12h").
- Escalation to a backup operator if the primary doesn't respond.

**Sweeper failure modes:**

| Failure | Recovery |
|---|---|
| Sweeper itself goes down (Cloud Run cold start fail, etc.) | Cloud Scheduler retries the next interval. Stale sessions accumulate but each will be drained as the sweeper comes back. |
| `resume_session(decision="timeout")` fails with a 404 (session was deleted out-of-band) | Catch, mark `terminated=True`, continue. Don't re-attempt deleted sessions. |
| Firestore query exceeds time limit | Query is bounded by the 24h window + max 1000 docs (paginated). At our volume (≤1 cycle/hour, 0.1% expected timeout rate), the query returns ≤1 doc per run. |

**Tests:**

- *sweeper_picks_up_stale_session* — Firestore mock with one 25h-old doc, assert `resume_session` called with `decision="timeout"`.
- *sweeper_skips_terminated_sessions* — already-terminated docs are ignored.
- *sweeper_failure_on_one_session_does_not_block_others* — first call raises, second succeeds.
- *sweeper_marks_terminated_after_resume* — Firestore doc gets `terminated=True` after resume.

### Decisions to challenge — chunk 6 §8

1. **No built-in timeout in `RequestInput`** — we bring our own via a
   separate Cloud Scheduler job + Firestore. Adds 2 moving parts
   (scheduler + bridge endpoint). Push back if you want to skip the
   sweeper and accept "stuck pauses" until the operator manually
   resumes or deletes them.
2. **Timeout decision is `"timeout"`** — distinct from `"skip"` /
   `"reject"`. Lets the workflow's terminal nodes record the right
   `cycle_outcome` for reporting. Push back if you'd rather collapse
   timeouts into skips.
3. **Sweeper runs every 15 min, timeout at 24h** — granularity ↔ load
   tradeoff. Tighter cadence (5 min) if SLA matters more.
4. **No escalation / nudge messages in v2** (§deferred to v3). Adds
   complexity (multi-stage notification state machine) for marginal
   value at our volume.

---

## §9 — Memory Bank schema

§9 is normative reference for the managed Memory Bank facts the
pipeline writes and reads. Implementations cite the field names defined
here verbatim — drift means the dedup logic stops working.

### §9.1 — Fact types

The pipeline writes exactly two fact types. Both live in the
`metadata.type` field of every fact.

#### `covered`

Written by `publisher` (§6.11) after a successful publication. Encodes
"we already wrote about this release; don't propose it again."

**Schema:**

```python
fact = f"Covered: {chosen_release.title}"
metadata = {
    "type":           "covered",
    "release_url":    chosen_release.url,        # primary dedup key
    "release_source": chosen_release.source,     # SourceType Literal value
    "covered_at":     <ISO 8601 UTC timestamp>,
    "bundle_url":     <GCS URL of the published article bundle>,
    "starter_repo":   <GitHub URL or None>,
}
scope = "ai_release_pipeline"
```

#### `human-rejected`

Written by `record_topic_verdict` (§6.3.2) on Topic Gate skip. Encodes
"the operator looked at this and said no."

**Schema:**

```python
fact = f"Human rejected topic: {chosen_release.title}"
metadata = {
    "type":           "human-rejected",
    "release_url":    chosen_release.url,
    "release_source": chosen_release.source,
    "rejected_at":    <ISO 8601 UTC timestamp>,
}
scope = "ai_release_pipeline"
```

**No other fact types in v2.** Notably:

| What we DON'T write | Why |
|---|---|
| `topic-gate-timeout` fact | Per §6.3.5 — timeout ≠ rejection; future cycles can re-surface. |
| `editor-rejected` fact | Per §6.9.4 — Editor rejection might be about draft quality, not the release. Allow re-attempt. |
| `editor-timeout` fact | Per §6.9.5 — same as topic timeout. |
| `triage-skipped` fact | Triage skip is algorithmic, not a "decision worth remembering." Re-evaluate next cycle. |

This minimalism is deliberate: **two fact types, two clear signals.**
v1 had four types; the extras created confusion about when to write
them and how Triage should weight them.

### §9.2 — Scope: `ai_release_pipeline`

All v2 facts live under one scope: `ai_release_pipeline`. Multi-tenant
is explicitly out of scope (§2 Non-goal 2).

**Why a scope at all?** Memory Bank's search API supports per-scope
isolation. Even though we have one tenant, scoping the writes:

1. **Future-proofs multi-tenant.** v3 can introduce per-org or per-bot
   scopes without a schema migration.
2. **Isolates from other agents in the same project.** If another
   project (e.g., a customer support bot) shares the Memory Bank
   instance, our scope means our facts don't leak.

**Implementation note:** the `tools/memory.py` adapter's
`memory_bank_search(query, scope="ai_release_pipeline", limit=5)`
defaults the scope so caller code rarely sets it explicitly. The
`scope` parameter is in the public API mainly so a v3 multi-tenant
swap doesn't require a global find-and-replace.

### §9.3 — Triage query semantics + similarity threshold

Triage (§6.2.1) queries Memory Bank once per candidate that scored ≥70
on the significance rubric. The contract:

**Query:**

```python
results = memory_bank_search(
    query=f"Have we encountered {candidate.title}?",
    scope="ai_release_pipeline",
    limit=5,
)
```

**Why phrase the query as a question?** Memory Bank's embedding
similarity works better with full-sentence queries than with bare
keywords. The phrasing also lets the embedding model focus on the
"identity" of the release rather than auxiliary terms.

**Result shape (per item):**

```python
{
    "fact":     "Covered: Anthropic Skills SDK",
    "score":    0.91,                         # similarity 0–1
    "metadata": {"type": "covered", "release_url": "...", ...},
}
```

**Decision rules — Triage applies these in order:**

1. **Iterate over results.** For each result `r`:
   - **Same URL match (exact):** if `r.metadata.release_url ==
     candidate.url`, treat as duplicate REGARDLESS of similarity score.
     This catches re-surfaces where the title may have drifted (e.g.
     a typo correction by the source) but the URL is stable.
   - **Hard reject (`type="human-rejected"`):** if
     `r.metadata.type == "human-rejected"` AND `r.score > 0.85`, drop
     the candidate. Operator already said no — don't ask again.
   - **Soft reject (`type="covered"`):** if `r.metadata.type ==
     "covered"` AND `r.score > 0.85`, drop the candidate. We already
     wrote about it.
2. **If no result triggers a drop, keep the candidate** for the
   highest-score selection.

**Similarity threshold: 0.85.** Inherited from v1. Tunable via
constant in `tools/memory.py`:

```python
DUPLICATE_SIMILARITY_THRESHOLD = 0.85
```

**Why 0.85 specifically?** v1 calibration: facts with score ≥0.85
shared the same release in 99%+ of test cases; 0.7–0.85 had ~30%
false-positive rate (different releases that happened to share keywords).
v2 inherits the threshold; we re-tune if production data shows drift.

**Why not embed-and-compare ourselves?** Memory Bank already does
embedding-based scoring server-side. Reimplementing would duplicate
work and lose the managed-service guarantees (model upgrades,
quota management).

### §9.4 — When Editor + Topic Gate write

Cross-reference table for "which decision causes a Memory Bank write":

| Outcome | Node that observes it | Memory Bank write? | Rationale |
|---|---|---|---|
| Triage skip (no candidate clears bar) | `record_triage_skip` | NO | Algorithmic filter; re-evaluate next cycle |
| Topic Gate approve | (handled by routing; no write needed here) | — | (publisher writes `covered` later) |
| Topic Gate skip | `record_topic_verdict` | YES — `human-rejected` | Operator decision; suppress future cycles |
| Topic Gate timeout | `record_topic_timeout` | NO | Operator wasn't available; re-surface OK |
| Critic loop (REVISE → drafter) | (none — internal to writer loop) | — | |
| Asset failures | (none — placeholders, no Memory Bank involvement) | — | |
| Editor approve | (handled by routing) | — | (publisher writes `covered` next) |
| Editor reject | `record_editor_rejection` | NO | Could be about draft, not release |
| Editor revise | `record_editor_verdict` | NO | Loop back; not a final decision |
| Editor timeout | `record_editor_timeout` | NO | Operator not available |
| Publisher (cycle published) | `publisher` | YES — `covered` | The canonical "we covered it" mark |

**Two nodes write Memory Bank in v2:**

1. `record_topic_verdict` (`human-rejected` on skip)
2. `publisher` (`covered` on successful publication)

**Both writes are best-effort.** Per §6.3.2 / §6.11, write failures log
but do NOT fail the cycle. Worst case: a release we already covered or
already rejected gets re-surfaced. Operator handles via Topic Gate skip.

### Decisions to challenge — chunk 6 §9

1. **Two fact types only** (`covered`, `human-rejected`). v1 had four.
   Push back if you want to add `topic-timeout-N-cycles-ago` style
   suppression facts.
2. **Hard URL match overrides similarity score.** Catches title
   drift but assumes URLs are stable. Push back if you've seen URL
   churn for the same release in the wild.
3. **Similarity threshold is 0.85 — same as v1.** No re-calibration
   in v2; tune after production data lands.
4. **Editor rejection writes NOTHING** — release CAN be re-surfaced.
   Push back if you want the rejection to be sticky (and rely on
   operator to manually un-stick via Memory Bank console).
5. **Scope is single-tenant `ai_release_pipeline`.** Multi-tenant is
   v3+. The scope parameter exists in the API so a future swap is
   localized.

---

## §10 — Deployment

§10 is the operator's reference for how every long-lived resource is
provisioned, what permissions it needs, and which secrets it reads.
Implementations cite this section directly.

### Deployment overview (3 resources to deploy + 4 supporting)

```
┌──────────────────────────────────────────────────────────────────────┐
│  ai-release-pipeline-v2                                              │
│   - kind: ReasoningEngine                                            │
│   - region: us-west1                                                 │
│   - source: deploy.py + agent.py + tools/ + nodes/ + shared/         │
│   - deployed via: vertexai.preview.reasoning_engines.ReasoningEngine │
│                                          .create(AdkApp(...))        │
└──────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────────┐
│  ai-release-pipeline-v2-telegram                                     │
│   - kind: Cloud Run service                                          │
│   - region: us-west1                                                 │
│   - container: telegram_bridge/Dockerfile                            │
│   - exposes: /telegram/webhook (Telegram POSTs here)                 │
│              /sweeper/escalate (Cloud Scheduler POSTs here)          │
└──────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────────┐
│  ai-release-pipeline-v2-hourly                                       │
│   - kind: Cloud Scheduler job                                        │
│   - region: us-west1                                                 │
│   - schedule: 0 * * * *  UTC  (PAUSED at create)                     │
│   - target: HTTP POST → ReasoningEngine :streamQuery endpoint        │
└──────────────────────────────────────────────────────────────────────┘
┌──────────────────────────────────────────────────────────────────────┐
│  ai-release-pipeline-v2-hitl-sweeper                                 │
│   - kind: Cloud Scheduler job                                        │
│   - schedule: */15 * * * *                                           │
│   - target: HTTP POST → telegram_bridge /sweeper/escalate            │
└──────────────────────────────────────────────────────────────────────┘
```

Supporting resources (provisioned once; never touched after):

| Resource | Notes |
|---|---|
| GCS bucket `gen-lang-client-0366435980-airel-assets-v2` | Asset hosting, 90-day lifecycle, public-read via uniform IAM |
| Memory Bank instance `airel-v2-memory` | Provisioned via `gcloud ai memory-banks create` (§15 Q2 resolution below) |
| Firestore database (Native mode, default) | Single collection `airel_v2_sessions` for the bridge lookup (§7.3.2) |
| Secret Manager: 3 secrets | See §10.4 |

---

### §10.1 — `AdkApp` + `ReasoningEngine` pattern

The pipeline deploys via the Vertex AI Agent Runtime SDK pattern that
the `memory-bank` ADK sample uses for its Agent Engine target.

**File: `deploy.py`** (the entire deploy entry point):

```python
# deploy.py
"""One-shot deployer for ai-release-pipeline-v2.

Run from the repo root:

    uv run python deploy.py

Reads project + region from .env (GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION).
Writes the resulting resource ID to deploy/.deployed_resource_id (gitignored).
"""

from __future__ import annotations

import os
import pathlib
import sys

import vertexai
from vertexai.preview import reasoning_engines

from agent import root_agent  # the Workflow declared in §5


PROJECT  = os.environ["GOOGLE_CLOUD_PROJECT"]
REGION   = os.environ["GOOGLE_CLOUD_LOCATION"]   # us-west1 per §3
DISPLAY  = "ai-release-pipeline-v2"
ID_FILE  = pathlib.Path("deploy/.deployed_resource_id")

REQUIREMENTS = [
    "google-adk==2.0.0b1",
    "google-cloud-aiplatform>=1.105",
    "google-cloud-storage>=2.14",
    "google-cloud-firestore>=2.14",
    "PyGithub>=2.3",
    "feedparser>=6.0",
    "arxiv>=2.1",
    "huggingface_hub>=0.25",
    "python-telegram-bot>=21",
    "pydantic>=2.5",
    "Pillow>=10.0",
    "requests>=2.32",
    # NOTE: ffmpeg-python intentionally omitted — v2 ships MP4-only
    # per §7.7 Q8.
]


def main() -> None:
    vertexai.init(project=PROJECT, location=REGION, staging_bucket=f"gs://{PROJECT}-airel-v2-staging")

    app = reasoning_engines.AdkApp(
        agent=root_agent,
        enable_tracing=True,        # Cloud Trace integration (§11.1)
    )

    # Update mode if the resource already exists (idempotent re-deploy).
    existing = _existing_resource_id()
    if existing:
        print(f"Updating existing engine: {existing}", file=sys.stderr)
        engine = reasoning_engines.ReasoningEngine(existing)
        engine.update(reasoning_engine=app, requirements=REQUIREMENTS)
    else:
        print("Creating new engine...", file=sys.stderr)
        engine = reasoning_engines.ReasoningEngine.create(
            app,
            requirements=REQUIREMENTS,
            display_name=DISPLAY,
            description="AI release → article pipeline (graph workflow + HITL)",
        )

    print(f"Resource: {engine.resource_name}")
    ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    ID_FILE.write_text(engine.resource_name + "\n")


def _existing_resource_id() -> str | None:
    if ID_FILE.exists():
        rid = ID_FILE.read_text().strip()
        if rid:
            return rid
    return None


if __name__ == "__main__":
    main()
```

**Why a single `deploy.py`** (vs. shell script + multiple steps)?
The Agent Runtime SDK is the only tool that knows how to package the
source tree and invoke `ReasoningEngine.create`. There's no separate
build step to wrap. One file = one entry point.

**Re-deploy semantics.** Running `deploy.py` a second time:
- Reads `.deployed_resource_id` if present.
- Calls `engine.update(...)` instead of `.create(...)` — same resource
  ID, new revision.
- Sessions and Memory Bank state survive across updates (Agent Runtime
  guarantee).

**Update vs. create cost.** `.update()` takes ~5 minutes (re-packages
source, restarts the runtime); `.create()` takes ~10 minutes (also
provisions the underlying serving infrastructure).

### §10.2 — Dependency pin

**`pyproject.toml` (the entire project deps section):**

```toml
[project]
name = "ai-release-pipeline"
version = "2.0.0"
description = "AI release → article pipeline on ADK 2.0 + Agent Runtime"
requires-python = ">=3.12"
dependencies = [
    # Pin to b1 — newer betas may introduce breaking changes.
    "google-adk==2.0.0b1",
    "google-cloud-aiplatform>=1.105,<2",
    "google-cloud-storage>=2.14,<3",
    "google-cloud-firestore>=2.14,<3",
    "PyGithub>=2.3,<3",
    "feedparser>=6.0,<7",
    "arxiv>=2.1,<3",
    "huggingface_hub>=0.25,<1",
    "python-telegram-bot>=21,<22",
    "pydantic>=2.5,<3",
    "Pillow>=10.0,<11",
    "requests>=2.32,<3",
]

[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "ruff>=0.5",
]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
```

**Pin policy:**

| Dep | Pin style | Why |
|---|---|---|
| `google-adk` | exact `==2.0.0b1` | Beta — any newer version may break Workflow API |
| `google-cloud-aiplatform` | range `>=1.105,<2` | Vertex SDK is stable; minor bumps OK |
| Everything else | range `>=X.Y,<Z` (next major) | Standard semver — minor + patch updates OK |

**`uv.lock`** is committed (reproducible installs). Re-lock with
`uv lock` when bumping any dep.

**Container vs. source-based deployment.** Agent Runtime is
**source-based** — the SDK packages the working directory and uploads.
No Dockerfile for the Workflow itself. (The Telegram bridge IS
containerized — different deploy target; see §10.6.)

**What's NOT in `pyproject.toml`:**
- `ffmpeg-python` — per §7.7 Q8, v2 ships without ffmpeg
- `imageio-ffmpeg` — same reason
- `vertexai` — bundled inside `google-cloud-aiplatform`

### §10.3 — Service account + IAM

Three service accounts, one per long-lived resource.

#### `airel-v2-app`

The Agent Runtime runtime SA. Provisioned via Terraform; the SDK
references it at deploy time via `service_account_email` parameter.

**Roles:**

| Role | On | Why |
|---|---|---|
| `roles/aiplatform.user` | project | Call Vertex models (Gemini, Imagen, Veo) |
| `roles/aiplatform.memoryBankUser` | the memory bank instance | Read + write facts (§9) |
| `roles/storage.objectAdmin` | the assets bucket | upload_to_gcs (§7.8) |
| `roles/datastore.user` | project | Firestore writes from `tools/telegram.py` (write the (prefix → full ID) lookup doc before posting Telegram) |
| `roles/secretmanager.secretAccessor` | each secret in §10.4 | Read GitHub PAT, Telegram bot token, webhook secret |
| `roles/logging.logWriter` | project | Standard for any agent emitting logs |
| `roles/cloudtrace.agent` | project | Cloud Trace export |

#### `airel-v2-telegram-bridge`

Cloud Run runtime SA for the bridge.

**Roles:**

| Role | On | Why |
|---|---|---|
| `roles/aiplatform.user` | project | Call `:streamQuery` to resume sessions |
| `roles/aiplatform.reasoningEngineUser` | the v2 ReasoningEngine | Resume specific session (more granular than aiplatform.user; preferred if available) |
| `roles/datastore.user` | project | Firestore lookup (`airel_v2_sessions` collection) |
| `roles/secretmanager.secretAccessor` | `airel-v2-telegram-bot-token`, `airel-v2-telegram-webhook-secret` | Verify webhook signature, post follow-ups |
| `roles/logging.logWriter` | project | Standard |

#### `airel-v2-scheduler`

Shared SA for both Cloud Scheduler jobs (hourly cron + 15-min sweeper).

**Roles:**

| Role | On | Why |
|---|---|---|
| `roles/run.invoker` | `ai-release-pipeline-v2-telegram` Cloud Run | Hits `/sweeper/escalate` |
| `roles/aiplatform.reasoningEngineUser` | the v2 ReasoningEngine | Hits `:streamQuery` directly (§10.5) |

**Token pattern:** Cloud Scheduler signs each HTTP request with an
OIDC ID token issued for the target audience (the Cloud Run URL or the
`:streamQuery` endpoint). The receiving service validates.

#### IAM principles

1. **Least privilege.** Each SA has only the roles it directly uses.
   No `roles/owner` or `roles/editor` anywhere in the v2 deployment.
2. **No SA impersonation.** v1 had a pattern where the bridge
   impersonated the runtime SA to call Vertex; v2 gives the bridge
   its own permissions.
3. **One SA per resource.** Mixing SAs across resources makes audit logs
   ambiguous ("which Cloud Run hit Vertex?"). Each Cloud Run / Scheduler
   / engine has a distinct identity.

### §10.4 — Secret Manager refs

Three secrets, all in Secret Manager (us-west1 replication):

| Secret name | Contents | Read by |
|---|---|---|
| `airel-v2-github-token` | Classic PAT with `repo` scope (no `delete_repo`) | `airel-v2-app` only (used by `repo_builder` LlmAgent) |
| `airel-v2-telegram-bot-token` | Bot token from @BotFather | `airel-v2-app` (post helpers) AND `airel-v2-telegram-bridge` (post follow-ups) |
| `airel-v2-telegram-webhook-secret` | Random 32-byte token; Telegram echoes it on every webhook call | `airel-v2-telegram-bridge` only (verify webhook signature) |

**Mounting into the Agent Runtime:**

`AdkApp` accepts a `secret_environment_variables` parameter on
`reasoning_engines.ReasoningEngine.create()`:

```python
engine = reasoning_engines.ReasoningEngine.create(
    app,
    requirements=REQUIREMENTS,
    display_name=DISPLAY,
    env_vars={
        "GOOGLE_CLOUD_PROJECT":         PROJECT,
        "GOOGLE_CLOUD_LOCATION":        REGION,
        "GOOGLE_GENAI_USE_VERTEXAI":    "true",
        "GITHUB_ORG":                   "pixelcanon",
        "TELEGRAM_APPROVAL_CHAT_ID":    "8481672863",
        "GCS_ASSETS_BUCKET":            f"{PROJECT}-airel-assets-v2",
        "MEMORY_BANK_BACKEND":          "vertex",
        "MEMORY_BANK_ID":               os.environ["MEMORY_BANK_ID"],
        "FIRESTORE_DATABASE":           "(default)",
    },
    secret_environment_variables=[
        {"variable_name": "GITHUB_TOKEN",        "secret_name": "airel-v2-github-token",        "version": "latest"},
        {"variable_name": "TELEGRAM_BOT_TOKEN",  "secret_name": "airel-v2-telegram-bot-token",  "version": "latest"},
    ],
)
```

(The webhook secret is mounted into the Cloud Run bridge separately —
see §10.6.)

**No secret strings in code, ever.** All secrets are Secret Manager
refs. `tools/*.py` modules read `os.environ["GITHUB_TOKEN"]` etc.;
they NEVER call Secret Manager directly.

**Rotation procedure:**

1. `gcloud secrets versions add airel-v2-github-token --data-file=<(echo -n "$NEW_PAT")`
2. Re-run `deploy.py` (re-mounts `latest`).
3. The platform-managed sidecar refreshes within ~60s.

### §10.5 — Cloud Scheduler trigger (resolves §15 Q3)

**Q3 resolution: Cloud Scheduler hits the Agent Runtime
`:streamQuery` endpoint directly via HTTP, with OIDC auth.** No Pub/Sub,
no Cloud Function. v1's Cloud Function only existed because Agent Engine
SDK calls weren't natively HTTP-callable from Scheduler in some SDK
versions; in 2026's Vertex API, the public `:streamQuery` endpoint
accepts standard HTTP POSTs.

**Cloud Scheduler job spec (Terraform):**

```hcl
resource "google_cloud_scheduler_job" "hourly" {
  name        = "ai-release-pipeline-v2-hourly"
  description = "Hourly trigger for the AI release pipeline v2"
  schedule    = "0 * * * *"
  time_zone   = "UTC"
  region      = "us-west1"
  paused      = true   # Operator unpauses after first manual smoke

  http_target {
    http_method = "POST"
    uri         = format(
      "https://%s-aiplatform.googleapis.com/v1/%s:streamQuery?alt=sse",
      var.location, google_vertex_ai_reasoning_engine.pipeline.id,
    )
    headers = {
      "Content-Type" = "application/json"
    }
    body = base64encode(jsonencode({
      class_method = "stream_query"
      input = {
        user_id    = "scheduler"
        message    = {
          role  = "user"
          parts = [{ text = "Run a polling cycle." }]
        }
      }
    }))
    oidc_token {
      service_account_email = google_service_account.scheduler.email
      audience              = format(
        "https://%s-aiplatform.googleapis.com/",
        var.location,
      )
    }
  }

  retry_config {
    retry_count = 1   # One retry on 5xx; we don't want 24h backoff loops
  }
}
```

**Why `oidc_token.audience` is the Vertex hostname (not the full
URL)?** Per Google's OIDC docs, the audience is the audience the
service account claims to address; for Vertex AI the canonical
audience is the regional hostname. Using the full request URL works
on some endpoints but isn't documented as guaranteed.

**Why no `session_id`?** The trigger is meant to start a NEW cycle
each time. Agent Runtime auto-creates a session if one isn't provided
and we omit `session_id` from the body. The `user_id="scheduler"`
makes the source identifiable in traces.

**Body shape — alternative considered.** We could pass
`{"trigger": "scheduler", "force_polling": true}` as state instead of a
text message. Decision: keep the message text-based for symmetry with
the Telegram bridge's resume calls (which also use the
`new_message` slot). Less surface area to test.

**Manual triggering for ad-hoc runs:**

```bash
gcloud scheduler jobs run ai-release-pipeline-v2-hourly --location=us-west1
```

(Recall §6.3.1 — the Topic Gate's `interrupt_id` hashes the URL, so a
manual trigger that lands on the same release as a still-paused cycle
will collide and "join" the pause rather than racing.)

### §10.6 — Telegram webhook (separate Cloud Run service)

The `telegram_bridge/` directory deploys as its own Cloud Run service
because (a) it needs a public HTTPS endpoint and (b) it must scale
independently of the Workflow's pause-resume cadence.

**Files:**

```
telegram_bridge/
  ├─ main.py                 # FastAPI app — see §7.3.2
  ├─ Dockerfile              # python:3.12-slim + uv + uv sync
  ├─ pyproject.toml          # tiny deps: fastapi, uvicorn, requests, google-auth, google-cloud-firestore
  └─ requirements.txt        # for the buildpack path if Dockerfile is removed later
```

**`Dockerfile`:**

```dockerfile
FROM python:3.12-slim
RUN pip install --no-cache-dir uv==0.8.13
WORKDIR /code
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen
COPY main.py ./
CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**Cloud Run config (Terraform):**

```hcl
resource "google_cloud_run_v2_service" "telegram" {
  name     = "ai-release-pipeline-v2-telegram"
  location = "us-west1"
  ingress  = "INGRESS_TRAFFIC_ALL"   # Telegram + Cloud Scheduler must reach it

  template {
    service_account = google_service_account.bridge.email
    timeout         = "30s"          # bridge calls drain 3 SSE events; 30s is plenty
    scaling {
      min_instance_count = 0          # Cold start ~3s acceptable
      max_instance_count = 5
    }
    containers {
      image = "us-west1-docker.pkg.dev/${var.project}/airel-v2/telegram-bridge:latest"
      ports { container_port = 8080 }
      env {
        name  = "AGENT_RUNTIME_ENDPOINT"
        value = format(
          "https://%s-aiplatform.googleapis.com/v1/%s",
          var.location, google_vertex_ai_reasoning_engine.pipeline.id,
        )
      }
      env {
        name  = "TELEGRAM_BOT_TOKEN"
        value_source { secret_key_ref { secret = "airel-v2-telegram-bot-token", version = "latest" } }
      }
      env {
        name  = "TELEGRAM_WEBHOOK_SECRET"
        value_source { secret_key_ref { secret = "airel-v2-telegram-webhook-secret", version = "latest" } }
      }
      env { name = "GOOGLE_CLOUD_PROJECT", value = var.project }
      env { name = "FIRESTORE_DATABASE",   value = "(default)" }
    }
  }

  traffic {
    percent = 100
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
  }
}
```

**Webhook URL registration (one-time, post-deploy):**

```bash
BRIDGE_URL=$(gcloud run services describe ai-release-pipeline-v2-telegram \
              --region=us-west1 --format='value(status.url)')
WEBHOOK_SECRET=$(gcloud secrets versions access latest --secret=airel-v2-telegram-webhook-secret)
curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=${BRIDGE_URL}/telegram/webhook" \
  -d "secret_token=${WEBHOOK_SECRET}" \
  -d "allowed_updates=[\"callback_query\",\"message\"]"
```

**`/sweeper/escalate` — Cloud Scheduler authentication.** Cloud
Scheduler hits this endpoint with an OIDC token whose audience is
`BRIDGE_URL`. The bridge validates the token (FastAPI dependency); the
sweeper SA needs `roles/run.invoker` on this Cloud Run.

### Decisions to challenge — chunk 7 §10

1. **Direct Cloud Scheduler → Agent Runtime HTTP trigger** (Q3
   resolution). No Pub/Sub, no Cloud Function. Push back if you want
   Pub/Sub for fan-out (we don't need it now — single subscriber).
2. **Telegram bridge is its own Cloud Run service** with its own SA,
   container, and Firestore write permission. Adds operational surface.
   Alternative: bundle inside Agent Runtime — rejected per §7.3.2.
3. **OIDC audience is the regional Vertex hostname** in §10.5. If
   Vertex docs change to require the full request URL as audience,
   this Terraform changes one line.
4. **`paused = true` at create time** (both for the hourly cron and the
   sweeper). Operator unpauses the cron after the first manual smoke;
   the sweeper unpauses immediately because it's safe to run from day 0.
5. **Three secrets only** (`github`, `bot-token`, `webhook-secret`).
   Memory Bank ID is NOT a secret — just an env var. Push back if you
   consider the bank ID sensitive.
6. **No CI/CD for v2** in this draft. Operator runs `deploy.py` from
   their workstation. If we want CI/CD (GitHub Actions, Cloud Build),
   it's an additive change to §10 in v2.1.

---

## §11 — Observability

§11 is the operator's reference for "what happened during cycle N?"
Everything is built on the Vertex Agent Runtime + Cloud Operations
stack. No third-party APM in v2.

### §11.1 — Cloud Trace (auto)

**`AdkApp(..., enable_tracing=True)` is the entire setup.** Agent
Runtime exports OpenTelemetry spans to Cloud Trace automatically.

**Span hierarchy per cycle:**

```
invocation (one per Workflow run)
└─ workflow.ai_release_pipeline_v2 (root)
   ├─ node.scout                              (LLM agent — instrumented)
   │  ├─ call_llm.gemini-3.1-flash-lite-preview
   │  ├─ execute_tool.poll_arxiv
   │  ├─ execute_tool.poll_github_trending
   │  ├─ execute_tool.poll_rss
   │  ├─ execute_tool.poll_hf_models
   │  ├─ execute_tool.poll_hf_papers
   │  ├─ execute_tool.poll_hackernews_ai
   │  └─ execute_tool.poll_anthropic_news
   ├─ node.triage
   │  ├─ call_llm.gemini-3.1-flash
   │  ├─ execute_tool.memory_bank_search
   │  └─ execute_tool.write_state_json (×N)
   ├─ node.route_after_triage                 (function node — short span)
   ├─ node.topic_gate_request                 (function node — yields RequestInput)
   │  └─ execute_tool.post_topic_approval
   ├─ <PAUSE — RequestInput suspended>        (no spans during pause)
   ├─ node.record_topic_verdict               (resumed; receives FunctionResponse)
   │  └─ execute_tool.memory_bank_add_fact    (only on skip)
   ├─ ... (rest of the graph)
   └─ node.publisher
      ├─ execute_tool.medium_format
      ├─ execute_tool.upload_to_gcs
      └─ execute_tool.memory_bank_add_fact
```

**Useful filters (Cloud Console → Trace → Trace explorer):**

| Goal | Filter |
|---|---|
| All cycles in last 24h | `service.name="ai_release_pipeline_v2" AND timestamp >= now-24h` |
| Cycles that hit Topic Gate | `name=~"node.topic_gate_request"` |
| Cycles that paused (any HITL) | `name=~"node.(topic_gate_request\|editor_request)" AND has(long_running_tool_ids)` |
| Cycles that timed out | `attributes.cycle_outcome IN ("topic_timeout", "editor_timeout")` |
| Slowest LLM calls | `name=~"call_llm" AND duration > 30s` |
| Failed tool calls | `name=~"execute_tool" AND status_code != "OK"` |

**Trace retention:** Cloud Trace's default 30-day retention is fine
for v2. If we want longer (e.g. 90d for trending analysis), upgrade
the project's retention setting — no code change.

**Trace ID propagation to Telegram:** the Topic Gate / Editor Telegram
messages should include a short trace ID suffix so the operator can
copy-paste into Cloud Console when something looks off:

```
"...Topic Gate: approve {title!r}? (score=N)\n[trace: {trace_id[:8]}]"
```

`{trace_id[:8]}` is enough to uniquely identify the cycle in trace
explorer's prefix search.

### §11.2 — Cloud Logging filters

**Resources that emit logs:**

| Resource | Log resource type | Notes |
|---|---|---|
| Agent Runtime ReasoningEngine | `aiplatform.googleapis.com/ReasoningEngine` | Workflow + node + tool stdout/stderr |
| Cloud Run telegram bridge | `cloud_run_revision` | Bridge access logs + business logs |
| Cloud Scheduler hourly + sweeper | `cloud_scheduler_job` | Cron firing + HTTP target results |
| Memory Bank API | `aiplatform.googleapis.com/MemoryBank` | Fact reads + writes (audit logs) |

**Useful queries (Cloud Logging Query Language):**

```
# 1. Every cycle outcome in the last 7 days, grouped by outcome
resource.type="aiplatform.googleapis.com/ReasoningEngine"
resource.labels.reasoning_engine_id="{ID}"
jsonPayload.cycle_outcome:*
| stats count by jsonPayload.cycle_outcome
| 7d

# 2. Most recent Triage skip reasons
resource.type="aiplatform.googleapis.com/ReasoningEngine"
jsonPayload.cycle_outcome="skipped_by_triage"
| limit 50

# 3. Telegram bridge errors
resource.type="cloud_run_revision"
resource.labels.service_name="ai-release-pipeline-v2-telegram"
severity >= ERROR

# 4. Sessions paused for >12h (early-warning before sweeper times them out)
resource.type="aiplatform.googleapis.com/ReasoningEngine"
labels.event_type="REQUEST_INPUT_YIELDED"
timestamp <= timestamp_sub(@now, INTERVAL 12 HOUR)

# 5. Tool failures by tool name
resource.type="aiplatform.googleapis.com/ReasoningEngine"
jsonPayload.tool_name:*
jsonPayload.status="error"
| stats count by jsonPayload.tool_name
| 24h
```

**Log-based metrics + alerts (provisioned via Terraform):**

| Metric | Alert |
|---|---|
| Count of cycles with `cycle_outcome="published"` per day | Alert if 0 for 48h (pipeline silent) |
| Count of `severity >= ERROR` from telegram bridge per hour | Alert if >5 per hour (bridge degraded) |
| Count of `cycle_outcome="topic_timeout"` per day | Alert if >2 per day (operator may be MIA) |
| Memory Bank API `add_fact` error rate | Alert if >10% over 1h (Memory Bank degraded — facts are best-effort but high error rate is a signal) |

### §11.3 — GenAI Evaluation Service

v1 used local `agents-cli eval run` against `tests/eval/evalsets/*.json`.
v2 uses the **GenAI Evaluation Service** (managed Vertex evaluation) for
production-grade scoring with Auto SxS.

**Surfaces:**

| Surface | Purpose | Cadence |
|---|---|---|
| **Per-cycle scoring** (live) | Score every published cycle on rubric items | Every cycle, post-publication |
| **Regression suites** | Run a curated set of fixtures monthly | Operator-triggered |
| **Auto SxS** (when migrating prompts) | Compare two prompt versions on the same fixtures | Per prompt change |

**Per-cycle rubric:**

```
1. Topic relevance (0-5):
   Does the published article actually cover the chosen release?
2. Factual accuracy (0-5):
   Are claims in the article supported by the research dossier?
3. Quickstart runnability (0-5, only for article_type=quickstart):
   Could a competent dev follow the article and reproduce the
   demonstrated capability?
4. Image-text coherence (0-5):
   Do the generated images match what the surrounding paragraphs
   describe?
5. Critic-Editor alignment (0-5):
   Did the Editor's verdict align with the Critic's structural
   feedback? (Catches cases where the LLM Critic accepts a draft the
   human Editor rejects.)
```

**Implementation hook:** `publisher` (§6.11) fires off a fire-and-forget
HTTP POST to the Evaluation Service after writing the `covered` fact.
Results land in BigQuery via the standard Evaluation Service sink.

**Pseudocode (added to `publisher`):**

```python
# nodes/publisher.py (continued from §6.11)
def _enqueue_scoring(cycle_outcome: dict, bundle_url: str) -> None:
    """Fire-and-forget evaluation enqueue. Failures are non-blocking."""
    try:
        # See: https://cloud.google.com/vertex-ai/generative-ai/docs/models/evaluation-overview
        scoring_request = {
            "name":       f"airel-cycle-{cycle_outcome['session_id']}",
            "inputs":     {"bundle_url": bundle_url, **cycle_outcome},
            "rubric_uri": "gs://{project}-airel-v2-rubrics/per_cycle_v1.yaml",
        }
        scoring_client.runs.start(request=scoring_request)
    except Exception as exc:
        logger.warning("scoring enqueue failed: %s", exc)
```

**Why fire-and-forget?** The scoring doesn't gate publication. We want
the article published whether scoring succeeds or not; the scoring
result lands in BigQuery for later trend analysis.

**Regression suite fixtures.** A small set of "golden" cycles stored
in `tests/eval/regression_v2/` — each is a (chosen_release fixture +
expected article topic + expected `cycle_outcome`) triple. Operator
runs the suite manually before any major prompt change:

```bash
uv run python tests/eval/run_regression.py --suite v2_default
```

The runner posts each fixture as a synthetic Pub/Sub trigger to a
**dedicated regression-mode ReasoningEngine** (separate from
production), waits for cycle completion, and asserts:

| Assertion | How |
|---|---|
| `cycle_outcome == expected` | Read final session state from Vertex Sessions API |
| Article mentions `chosen_release.title` | Substring search in `final_markdown` |
| Image asset count == `len(image_briefs)` | Compare list lengths |
| Memory Bank `covered` fact written | Query Memory Bank for the URL |

**Open question for v2.1:** auto-trigger the regression suite on
prompt changes via GitHub Actions. Out of scope for initial v2 (no
CI/CD per §10 decision 6).

### Decisions to challenge — chunk 7 §11

1. **Cloud Trace is the only tracing backend in v2.** No third-party
   APM (Datadog, AgentOps, Phoenix, etc.). Push back if you want one
   of those for richer agent-specific UI.
2. **Trace ID prefix appended to Telegram messages** for operator
   debugging. Adds 12 chars to every Telegram post. Alternative: include
   only on Editor messages (when an operator is most likely to need it).
3. **GenAI Evaluation Service is fire-and-forget from `publisher`.**
   Scoring failure does NOT fail the cycle. Push back if you want hard
   coupling (rare; usually scoring is for trend-tracking, not gating).
4. **Regression suite needs a dedicated regression-mode
   ReasoningEngine.** Adds a 2nd deployment. Alternative: run
   regression cycles against production with a `regression=true` tag
   and filter them out of stats. Cleaner separation chosen.
5. **Log-based metrics in v2 are the four listed.** Each comes with an
   alert. Add more as production behavior reveals them.

---

## §12 — Failure modes & recovery

§12 is the cross-cutting failure playbook. Every per-node and per-tool
section in §6/§7 lists its own failure modes; this section summarizes
the **classes** of failure, the **detection signal**, the **blast
radius** (what fails, what continues), and the **recovery** (manual or
automatic).

The six classes below cover every failure mode named in §6 and §7. If
production surfaces a class not on this list, we add it here AND patch
the relevant §6/§7 section.

### §12.1 — LLM call fails

**What it covers.** Any `call_llm` span (Gemini Vertex calls) that
returns an error: 4xx (auth, model-not-found, safety-filter), 5xx
(transient backend), timeout, or empty content.

**Detection.**
- Cloud Trace span has `status_code != "OK"`.
- Cloud Logging entry from the calling node with `severity >= ERROR`.
- Operator-facing: the cycle either retries (transient errors) or ends
  with `cycle_outcome="rejected_by_editor"` (Editor sees broken state)
  or fails to produce a paused HITL — operator notices the absence.

**Blast radius by node:**

| Failing node | Blast radius |
|---|---|
| `scout` | `candidates=[]` → Triage skip → `cycle_outcome="skipped_by_triage"`. Cheap recovery. |
| `triage` | `chosen_release=None` (Pydantic default) → `route_after_triage` → SKIP. Cheap recovery. |
| Any `*_researcher` | The respective `*_research` dossier stays None → `gather_research` produces a thinner merged dossier → Architect produces a weaker outline → likely Editor revises or rejects. Recoverable via revise loop. |
| `architect_llm` | `_architect_raw` empty → `architect_split` raises `ValueError("architect produced no JSON")` → workflow fails fast with a clear error. Operator re-triggers. |
| `drafter` / `revision_writer` | `draft.markdown` malformed → `critic_split` forces revise → loop iteration cap eventually forces ACCEPT or operator rejects via Editor. |
| `critic_llm` | `_critic_raw` empty/malformed → `critic_split` coerces to `verdict="revise"` → loop continues. Same recovery as drafter failure. |
| `image_asset_agent` | Per-image placeholder; cycle continues. Editor sees broken images. |
| `repo_builder` | `starter_repo=None`; cycle continues to Editor with `needs_repo=True` but no repo. Editor sees the broken state. |

**Recovery — automatic:**
- ADK retries `call_llm` 3× on 5xx (Vertex SDK default). No code change.
- Workflow continues per blast radius above; failures are absorbed at
  the next routing decision or HITL gate.

**Recovery — manual:**
- Persistent 4xx (auth, model 404): operator rotates secret or fixes
  model env var (e.g. `NANO_BANANA_MODEL`, `VEO_MODEL`), re-runs
  `deploy.py`.
- Safety filter blocks (model returns no candidates): operator may
  need to revise the prompt to avoid the trigger; tracked in §13.3
  regression suite.

### §12.2 — Tool call fails

**What it covers.** Any `execute_tool` span that returns an error.
Tool wrappers in `tools/*.py` follow a fail-open contract — most
return `[]` or `None` or a placeholder rather than raising.

**Detection.**
- Cloud Trace tool span has `status_code != "OK"` (when tools surface
  errors via raise) OR the tool returns `[]` / `None` and downstream
  nodes log "no result from {tool}".
- Cloud Logging entry from `tools/*.py` with `logger.warning("X failed: %s", e)`.

**Blast radius by tool category:**

| Tool category | Failure → behavior |
|---|---|
| Pollers (§7.1) | Single-poller fail → empty list for that source; Scout combines remaining. ALL pollers fail → Triage skip. |
| `web_fetch` | Returns `""`; researchers degrade gracefully. |
| `google_search` (built-in) | Empty result list; researchers fall back to `web_fetch` of the chosen_release.url alone. |
| `github_get_*` | Returns `{"error": "..."}`; github_researcher writes empty dossier. |
| `github_create_repo` / `_commit_files` | `starter_repo=None`; cycle continues, Editor sees the broken state. |
| `generate_image` | Per-image placeholder; cycle continues. |
| `generate_video` | `video_asset=None`; cycle continues, video marker dropped from final markdown. |
| `upload_to_gcs` | Caller (Imagen / Veo / Publisher) catches; assets become placeholders or cycle fails (Publisher's bundle upload is the only hard-fail path — see §6.11). |
| `medium_format` | Pure function; only fails on truly malformed input → Publisher fails the cycle. Acceptable rare path. |
| `memory_bank_*` | Returns `[]` / False; Triage / record nodes / Publisher continue without dedup info. |
| `post_topic_approval` / `post_editor_review` | HITL function nodes catch and... actually, they don't catch — Telegram failures propagate. **TODO chunk 8 fix:** wrap in retry-with-backoff per §6.3.1 failure modes table. (Already noted there as a future enhancement.) |

**Recovery — automatic:** fail-open contract above. Workflow continues
on most tool failures.

**Recovery — manual:** for repeated failures of the same tool (e.g.
GitHub rate limit), operator either waits out the limit or rotates
credentials.

### §12.3 — Memory Bank unavailable

**What it covers.** Vertex Memory Bank API returns 5xx, quota
exceeded, or the configured `MEMORY_BANK_ID` is wrong.

**Detection.**
- `memory_bank_search` returns `[]` (logged as warning).
- `memory_bank_add_fact` returns `False` (logged as error).
- Cloud Logging filter: `resource.type="aiplatform.googleapis.com/MemoryBank" AND severity >= ERROR` (per §11.2 query #4).
- Alert from §11.2 metric: `add_fact` error rate > 10% over 1h.

**Blast radius:**

| Affected operation | Behavior |
|---|---|
| Triage's novelty check | Returns `[]` → Triage proceeds without dedup info → may pick a release we already covered → Topic Gate operator skips it (writes `human-rejected`) → re-suppressed on next cycle once Memory Bank recovers. |
| `record_topic_verdict` skip-write | Returns `False` → human rejection NOT persisted → release MAY re-surface next cycle. Operator skips again. Slight friction; not a bug. |
| `publisher` covered-write | Returns `False` → `memory_bank_recorded=False` in state → article IS published → release MAY re-surface (Triage will see the matching URL via `release_url` exact match — see §9.3 — once the Memory Bank fact is finally persisted; until then, no dedup). |

**Recovery — automatic:** none. Memory Bank is a managed service; we
rely on Vertex SLA. Cycles continue without dedup until it recovers.

**Recovery — manual:**
- For sustained outage (>1h): operator switches `MEMORY_BANK_BACKEND`
  env var to `inmemory` for the immediate term (loses cross-cycle
  state but keeps cycles running) and re-deploys via `deploy.py`. Not
  ideal — note that the inmemory backend resets on each
  ReasoningEngine restart.
- For wrong `MEMORY_BANK_ID`: operator fixes the env var and re-deploys.

**Cost of running without dedup:** at hourly cadence, a single
operator can manually skip ~24 re-surfaces/day via Topic Gate. Not
sustainable for >24h outage; alert triggers hard escalation.

### §12.4 — Telegram down

**What it covers.** Telegram Bot API returns 4xx (token revoked, chat
deleted) or 5xx (Telegram outage); Telegram webhook callback fails to
reach the bridge (DNS, bridge cold-start failure).

**Detection.**
- `tools/telegram.py:post_*` raises → HITL function node fails → cycle
  fails fast with a clear error. The yielding node never gets to yield
  `RequestInput`.
- Bridge logs at `severity >= ERROR` (alert per §11.2 metric).
- No callback received within 24h → sweeper fires `decision="timeout"`
  → cycle terminates gracefully.

**Blast radius:**

| Failure | Effect |
|---|---|
| `post_topic_approval` raises (Telegram down at Topic Gate) | Cycle fails before pause. Operator sees the failure in Cloud Logging; re-triggers manually after Telegram recovers. |
| `post_editor_review` raises | Same — cycle fails before Editor pause. Operator re-triggers; the writer loop already produced a draft, so the re-trigger MIGHT re-do all the work. v2.1 candidate: persist draft pre-Editor so a re-trigger picks up where it left off. |
| Bridge down (Cloud Run cold-start fail, container crash) | Telegram retries the webhook (Telegram retries non-200 for ~24h). Bridge recovers, processes the queued callback. Operator sees a delayed pipeline. |
| Telegram delivery delay | Operator just sees the message later. Pipeline waits in the paused state; no impact until the 24h sweeper. |

**Recovery — automatic:**
- Telegram webhook delivery: Telegram's built-in retry covers transient
  bridge failures.
- Sweeper: stuck pauses get cleared after 24h.

**Recovery — manual:**
- Sustained Telegram outage: operator manually resumes paused sessions
  via direct API calls to `:streamQuery`. Tedious but possible.
- Bot token revoked: rotate the secret, re-register the webhook URL.

### §12.5 — `RequestInput` timeout (24h+)

**What it covers.** The case where a paused HITL session has waited
>24h for a human response. Mechanically already handled by the sweeper
(§8.4); included here for the operator's mental model.

**Detection.**
- Cloud Logging query #4 from §11.2 surfaces sessions paused >12h
  (early warning).
- Sweeper runs every 15 min; logs every escalation (`{"timed_out": N}`).
- `record_topic_timeout` / `record_editor_timeout` set `cycle_outcome="*_timeout"` — surfaces in metric counts (§11.2 alert: >2 topic_timeouts/day).

**Blast radius.** Bounded to one cycle per timeout. No state leak —
sessions are deleted (Firestore doc gets `terminated=True`; Vertex
session expires per its own TTL).

**Recovery — automatic:** sweeper handles it; cycle ends with the
`*_timeout` outcome; no manual intervention needed.

**Recovery — manual:**
- Operator can manually resume a paused session BEFORE the 24h timeout
  via `gcloud ai reasoning-engines stream-query ...` with a hand-crafted
  FunctionResponse. Useful for "I forgot to approve" scenarios.

### §12.6 — Asset generation 404 / quota

**What it covers.** Imagen and Veo specifically. Models 404 (wrong ID
in env), quota exhausted (project hits daily limit), safety filter
blocks the prompt.

**Detection.**
- Cloud Trace tool span for `generate_image` / `generate_video` has
  `status_code != "OK"`.
- Cloud Logging entry from `tools/imagen.py` / `tools/veo.py`.
- Operator-facing: per-image placeholders show up in Editor preview.

**Blast radius:** per-image / per-video. Cycle continues. Editor sees
the broken assets and revises (asks for different image briefs) or
rejects.

**Recovery — automatic:** Per-asset fail-open. Cycle proceeds with
placeholders; Editor decides.

**Recovery — manual:**
- Wrong model ID: operator fixes `NANO_BANANA_MODEL` / `VEO_MODEL` env
  var, re-runs `deploy.py`. (v1 Bug B4 was exactly this.)
- Quota: operator requests quota increase via GCP console or waits for
  daily reset.
- Safety filter: operator inspects prompt; usually fixable by
  rephrasing the brief.

### §12.7 — Cross-cutting: state corruption (the "shouldn't happen but")

**What it covers.** State invariants from §4 violated mid-cycle. e.g.
`chosen_release` becomes None mid-research-pool. **Should not happen
in v2** (routing prevents it; Pydantic schema enforces it), but if it
does:

**Detection.**
- Defensive logs in `record_*` nodes (§6.2.3, §6.3.4 etc.) fire when
  state is inconsistent.
- Cloud Trace shows nodes running that "shouldn't" given state.

**Recovery:** cycle ends with whatever `cycle_outcome` the terminal
node sets. Operator inspects the trace and files a bug; v2.1 fixes the
routing or schema gap.

### Decisions to challenge — chunk 8 §12

1. **No retry-with-backoff for Telegram posts** in v2 (TODO flagged in
   §12.2). Push back if you want it now — adds ~30 lines to
   `tools/telegram.py`.
2. **No "draft persistence pre-Editor"** so a re-trigger picks up
   where the previous run left off. v2.1 candidate. Push back if you
   want it now — adds a "draft cache" layer with its own staleness
   semantics.
3. **Memory Bank outage falls back to inmemory MANUALLY** (operator
   sets the env var and re-deploys). Push back if you want automatic
   degradation (with the cross-cycle state loss it implies).

---

## §13 — Eval strategy

§13 documents the testing tiers v2 will ship with. Three tiers, each
catches different bug classes:

```
        ┌─────────────────────────────────────────────┐
        │ §13.1 Unit tests (per tool)                 │  fast,  100s of tests
        │  - tools/*.py                               │  every commit
        │  - nodes/*.py                               │
        └────────────────────┬────────────────────────┘
                             │
                             ▼
        ┌─────────────────────────────────────────────┐
        │ §13.2 Workflow tests (mocked LLM, real graph)│  slow,  ~10 cases
        │  - exercises Workflow construction          │  every commit
        │  - exercises edges, routing, HITL pause      │  (CI candidate)
        │  - LLMs mocked; tools optionally mocked      │
        └────────────────────┬────────────────────────┘
                             │
                             ▼
        ┌─────────────────────────────────────────────┐
        │ §13.3 Live evaluation (GenAI Eval Service)   │  slowest,  per cycle
        │  - per-cycle rubric scoring (auto)          │  + monthly regression
        │  - regression suites (operator-triggered)    │
        │  - Auto SxS (per prompt change)             │
        └─────────────────────────────────────────────┘
```

### §13.1 — Unit tests (per tool, per function node)

**Coverage target:** 100% of code in `tools/*.py` and `nodes/*.py`,
measured by `pytest --cov=tools --cov=nodes`.

**Source of tests:**

| Layer | Source | Status |
|---|---|---|
| Pollers (`tools/pollers.py`) | `tests/test_scout.py` (25 tests, port from v1) | **Carry over verbatim** — already covers all 7 pollers + ISO-string regression + dedup + cap |
| Web fetch (`tools/web.py`) | `tests/test_researchers.py` portion | Carry over |
| GitHub ops (`tools/github_ops.py`) | `tests/test_repo_builder.py` portion | Carry over |
| GCS (`tools/gcs.py`) | `tests/test_assets.py` portion | Carry over + add v2 default-bucket test |
| Imagen (`tools/imagen.py`) | `tests/test_assets.py` portion | Carry over + assert default model is `-001` not `-preview` |
| Veo (`tools/veo.py`) | `tests/test_assets.py` portion | Carry over + assert MAX_DURATION clamping |
| Medium (`tools/medium.py`) | `tests/test_writer.py` portion | Carry over |
| Memory Bank (`tools/memory.py`) | **NEW** | Tests the adapter pattern (see §7.2 test list) |
| Telegram (`tools/telegram.py`) | **NEW** (port v1's structural tests + add callback_data byte-budget tests) | See §7.3.1 |
| Function nodes (`nodes/*.py`) | **NEW** | One test file per node module (`tests/test_routing.py`, `tests/test_records.py`, etc.); each test is fast (no LLM, no network) |

**Test count estimate:**

| Module | Test count |
|---|---|
| `tools/pollers.py` | 25 (v1) |
| `tools/{web,github_ops,gcs,medium,imagen,veo}.py` | ~40 (v1) |
| `tools/memory.py` | ~6 (new) |
| `tools/telegram.py` | ~5 (new) |
| `nodes/routing.py` (5 routers × ~3 cases each) | ~15 |
| `nodes/hitl.py` (2 nodes × ~5 cases) | ~10 |
| `nodes/records.py` (7 nodes × ~3 cases) | ~21 |
| `nodes/aggregation.py` (2 nodes × ~3 cases) | ~6 |
| `nodes/architect_split.py` | ~10 (per §6.5.2 test list) |
| `nodes/critic_split.py` | ~7 (per §6.6.3) |
| `nodes/video_asset.py` | ~6 (per §6.7.2 — including the Bug B2 regression test) |
| `nodes/publisher.py` | ~9 (per §6.11) |
| **Total** | **~160 unit tests** |

**Run cadence:** every commit, locally + (when CI lands per §10
decision 6) in CI.

**Forbidden patterns:**
- ❌ Tests that assert on LLM output content (e.g. "agent says hello").
  Per `~/.claude/CLAUDE.md` — non-deterministic, belongs in eval.
- ❌ Tests that hit live external services without an `--live` flag or
  env-var gate. Live tests live in `tests/smoke/*.py` with explicit
  skip-on-missing-creds.

### §13.2 — Workflow tests (mocked LLM, real graph)

**Goal.** Exercise the `Workflow(edges=[...])` itself — routing,
HITL pause/resume, terminal node selection, state mutation propagation
— without consuming LLM tokens. Catches bugs in the graph topology
that unit tests can't see.

**Pattern (one test, abridged):**

```python
# tests/test_workflow.py
import pytest
from unittest.mock import patch, MagicMock
from google.adk.runners import InMemoryRunner
from google.genai import types as genai_types

from agent import root_agent

@pytest.mark.asyncio
async def test_low_significance_cycle_ends_at_record_triage_skip():
    """When Triage writes chosen_release=None, the workflow should run
    Scout -> Triage -> route_after_triage -> record_triage_skip and END
    (cycle_outcome="skipped_by_triage"). No LLM tokens consumed.
    """
    # Mock all 11 LLM agents to return canned responses.
    # Mock all polling tools to return empty lists.
    # Force Triage's _coerce_decision to write chosen_release=None.
    with patch("agents.scout.scout.run_async", _mock_scout_returning([])), \
         patch("agents.triage.triage.run_async", _mock_triage_writing_skip()):
        runner = InMemoryRunner(agent=root_agent, app_name="test")
        sess = await runner.session_service.create_session(app_name="test", user_id="t")
        msg = genai_types.Content(role="user", parts=[genai_types.Part.from_text(text="run")])
        async for _ in runner.run_async(user_id="t", session_id=sess.id, new_message=msg):
            pass
        final = await runner.session_service.get_session(app_name="test", user_id="t", session_id=sess.id)
        assert final.state["cycle_outcome"] == "skipped_by_triage"
        assert final.state.get("topic_verdict") is None  # Topic Gate never ran
```

**Cases to cover (~10 tests, one per termination path):**

| Test | Asserts the workflow reaches |
|---|---|
| `test_low_significance_cycle_ends_at_record_triage_skip` | `cycle_outcome="skipped_by_triage"` |
| `test_topic_gate_skip_writes_human_rejected` | `cycle_outcome="skipped_by_human_topic"` + Memory Bank fact captured by mock |
| `test_topic_gate_timeout_clears_chosen_release` | `cycle_outcome="topic_timeout"` |
| `test_happy_path_publishes_with_assets_no_repo` | `cycle_outcome="published"` + state has `final_markdown`, `asset_bundle_url`, no `starter_repo` |
| `test_happy_path_with_repo` | Same + `starter_repo` present |
| `test_writer_loop_terminates_at_iteration_3` | Critic always says "revise"; assert `writer_iterations==3` and `cycle_outcome="published"` |
| `test_editor_revise_loop_terminates_at_iteration_3` | Editor always says "revise"; assert `editor_iterations==3` and `cycle_outcome="rejected_by_editor"` (forced reject per §6.9.2) |
| `test_editor_reject_writes_no_memory_bank_fact` | Mock memory bank; assert no calls during the reject path |
| `test_video_asset_or_skip_does_not_call_veo_when_needs_video_false` | The Bug B2 regression test from §6.7.2 |
| `test_revise_loop_preserves_image_markers_after_revision_writer` | Revision writer rewrites; final draft still has `<!--IMG:hero-->` |

**Test fixtures.** A handful of canned responses live in
`tests/fixtures/` (e.g. `architect_blob_quickstart.json`,
`critic_revise.json`, `chosen_release_anthropic.json`). One file per
LLM "response shape" so tests don't repeat themselves.

**Run cadence:** every commit. Each test ~1–2s (no network); full
suite ~20s.

### §13.3 — Live evaluation (GenAI Evaluation Service)

Detailed in §11.3. Recap of the three surfaces:

| Surface | Cadence | What it catches |
|---|---|---|
| Per-cycle scoring (auto, fire-and-forget) | Every published cycle | Topic relevance, factual accuracy, image-text coherence — measured by Vertex's managed evaluators |
| Regression suite | Operator-triggered, monthly | Behavior regression: a fixture cycle that used to publish now skips, or a "should-skip" fixture starts publishing |
| Auto SxS | Per prompt change | Does the new prompt do better than the old on the same fixtures? |

**Boundary between §13.2 and §13.3.** §13.2 tests the GRAPH (routing,
state, termination). §13.3 tests the BEHAVIOR (does the article
actually cover the right release? are the claims accurate? is the
quickstart runnable?). §13.2 mocks LLMs; §13.3 uses real LLMs and
real Memory Bank but a separate (regression-mode) ReasoningEngine.

### §13.4 — Test ownership table

| Test surface | Owner | Run when | Failure means |
|---|---|---|---|
| pytest unit tests | Operator | Every commit | A specific function broke; fix and re-commit |
| Workflow tests (§13.2) | Operator | Every commit | The graph topology broke; fix `agent.py` `edges=[...]` |
| Per-cycle live scoring | GenAI Eval Service | Every cycle | A signal — track in BigQuery; investigate trends not individual scores |
| Regression suite | Operator | Before any major prompt change | A fixture moved; investigate whether the prompt change is the cause |
| Auto SxS | Vertex | Per prompt change | Statistical comparison — operator decides whether to ship the new prompt |

### Decisions to challenge — chunk 8 §13

1. **No "test that assert on LLM output content" in pytest** — strict
   per `~/.claude/CLAUDE.md`. All such assertions live in §13.2
   (mocked) or §13.3 (live evaluation).
2. **Workflow tests mock LLMs entirely.** Push back if you want a tier
   that uses real LLMs but mocks tools (intermediate cost between
   §13.2 and §13.3). Adds noise without much catch.
3. **No code coverage gate** in v2 (we don't fail CI under 80%).
   Coverage target is 100% but enforcement is by-eye for now. Push back
   if you want hard gate.

---

## §14 — What survives v1 → v2

Per chunk 1's authoring rules, v1 is dead on arrival; v2 is a fresh
build. The following is the explicit "what gets ported, what gets
deleted" table so nothing valuable is lost in translation.

### Files / modules — survives v1 → v2 status

| v1 path | v2 status | Notes |
|---|---|---|
| **`tools/`** | | |
| `tools/pollers.py` | **KEEP — verbatim** | All 7 pollers already fixed and live-tested in v1's working tree (§7.1) |
| `tools/web.py` | **KEEP — verbatim** | Stdlib-only, no churn (§7.4) |
| `tools/github_ops.py` | **KEEP — verbatim** | Atomic Git Data API commits already work (§7.5) |
| `tools/gcs.py` | **KEEP — verbatim with bucket name updated** | New default `*-airel-assets-v2` (§7.8) |
| `tools/imagen.py` | **KEEP — verbatim** | Default model already fixed to `-001` in v1 (§7.6) |
| `tools/veo.py` | **KEEP — verbatim, Veo model env TBD** | §15 Q6 |
| `tools/medium.py` | **KEEP — verbatim** | Pure stdlib (§7.9) |
| `tools/video_processing.py` | **DELETE** | v2 ships MP4-only; no GIF/poster derivation (§7.7 + §15 Q8) |
| `tools/telegram_approval.py` | **DELETE** | Replaced by `tools/telegram.py` (post helpers) + `telegram_bridge/` (separate Cloud Run) (§7.3) |
| **`shared/`** | | |
| `shared/models.py` | **REWRITE — extend** | Carry all 13 v1 Pydantic models verbatim; ADD `PipelineState`, `StarterRepo`, `ArticleType` literal, `EditorDecision` literal, `TopicDecision` literal (§4) |
| `shared/prompts.py` | **REWRITE** | Carry the prompt TEXT for SCOUT, TRIAGE, *_RESEARCHER, ARCHITECT, DRAFTER, CRITIC, IMAGE_ASSET, REPO_BUILDER, EDITOR, REVISION_WRITER. **Drop** the `_EARLY_EXIT_PREAMBLE` (function nodes enforce, not prompts). **Update** SCOUT to list 7 pollers. **Update** ARCHITECT to mandate the JSON shape architect_split parses (§6.5.1). |
| `shared/memory.py` | **DELETE** | Replaced by `tools/memory.py` thin adapter to `VertexAiMemoryBankService` (§7.2) |
| **`agents/`** | | |
| `agents/scout/agent.py` | **REWRITE** as `agents/scout.py` | LlmAgent definition; tools list updated (7 pollers); model unchanged. ~15 lines. |
| `agents/triage/agent.py` | **REWRITE** as `agents/triage.py` | Same shape (LlmAgent + 2 tools); model bumps to `gemini-3.1-flash`. |
| `agents/topic_gate/agent.py` | **DELETE** | v2's Topic Gate is 5 function nodes (§6.3), not an LlmAgent. |
| `agents/researchers/{docs,github,context}.py` | **REWRITE** consolidate to `agents/researchers.py` | 3 LlmAgents in one file. |
| `agents/architect/agent.py` | **REWRITE** as `agents/architect.py` | Just `architect_llm` (LlmAgent). Splitter logic moves to `nodes/architect_split.py`. |
| `agents/writer/{drafter,critic}.py` | **REWRITE** consolidate to `agents/writer.py` | `drafter` + `critic_llm` LlmAgents. Critic-split logic moves to `nodes/critic_split.py`. |
| `agents/asset/{image,video}.py` | **REWRITE — only image** as `agents/assets.py` | Just `image_asset_agent` LlmAgent. Video becomes `nodes/video_asset.py` function node. |
| `agents/repo_builder/agent.py` | **REWRITE** as `agents/repo_builder.py` | Same LlmAgent; no router-LLM wrapper (§6.8). |
| `agents/revision_writer/agent.py` | **REWRITE** as `agents/revision_writer.py` | Same LlmAgent. |
| **Top-level / wrappers** | | |
| `main.py` | **REWRITE** as `agent.py` | The `Workflow(edges=[...])` declaration (§5). |
| `pipeline/` | **DELETE** | Was the `adk web` wrapper for v1. v2 uses Agent Runtime + AdkApp, no `adk web` path. |
| `app/` | **DELETE** | Was the agents-cli wrapper for v1. v2 uses `deploy.py` (§10.1). |
| `Dockerfile` | **DELETE** | Agent Runtime is source-based; no Dockerfile for the workflow itself. |
| `deploy/` | **DELETE most; rewrite scheduler.tf** | All Terraform from v1's Cloud Run target gets replaced by v2's Agent Runtime + Cloud Run bridge + 2 Schedulers Terraform. The bridge `deploy/cloud_function/` is gone (no Cloud Function in v2). |
| **`tests/`** | | |
| `tests/test_scout.py` | **KEEP** | 25 tests cover the pollers; carries over |
| `tests/test_triage.py` | **PORT** | Carry over the score+novelty tests; rewrite the agent-wiring tests for v2 |
| `tests/test_topic_gate.py` | **REPLACE** with `tests/test_hitl.py` + `tests/test_records.py` | v2 split topic gate logic across multiple function nodes; tests follow |
| `tests/test_researchers.py` | **PORT** | Carry over the dossier-shape tests |
| `tests/test_architect.py` | **PORT** | Carry over architect prompt tests; ADD `tests/test_architect_split.py` for the new function node |
| `tests/test_writer.py` | **PORT** | Same idea |
| `tests/test_assets.py` | **PORT** | Carry over Imagen + GCS tests; ADD `tests/test_video_asset.py` for the new function node |
| `tests/test_repo_builder.py` | **PORT** | Carry over |
| `tests/test_editor.py` | **PORT** | Carry over Editor verdict-coercion tests; ADD `tests/test_records.py` for the new recording function nodes |
| `tests/test_revision_writer.py` | **PORT** | Carry over |
| `tests/test_root_agent.py` | **REPLACE** with `tests/test_workflow.py` | v2's graph composition is fundamentally different (§13.2) |
| `tests/test_deploy.py` | **REPLACE** | v1 was about Cloud Run + Cloud Function; v2's deploy tests assert AdkApp pattern + Cloud Scheduler HTTP target |
| `tests/eval/evalsets/*.json` | **REPLACE** | v1's evalsets were structured for `agents-cli eval run`; v2 uses GenAI Evaluation Service rubric YAMLs (§11.3) |
| `tests/smoke/pollers_smoke.py` | **KEEP** | The live-network smoke that validated 11/10 sources in v1 |
| `tests/smoke/{telegram,gcs,github,memory,imagen,veo}_smoke.py` | **KEEP** | Same fail-on-missing-creds pattern; useful for operator pre-deploy validation |
| **Other** | | |
| `DESIGN.md` (v1) | **DELETE after v2 ships to staging** | History preserved in git |
| `DESIGN.v2.md` (this doc) | **PROMOTE TO `DESIGN.md`** | Once v2 is green |
| `audit_report.md` (in /tmp from v1) | **DISCARD** | Stale — v2 has its own per-section "decisions to challenge" |
| `deployment_report.md` (in /tmp from v1) | **DISCARD** | Same |
| `spike/` | **KEEP for ~30 days** | Reference for how each ADK 2.0 mechanic was validated; can delete after v2 ships |
| `.env.example` | **REWRITE** | Add `MEMORY_BANK_ID`, `MEMORY_BANK_BACKEND`, drop v1's GCS bucket env that referred to `*-airel-assets` (now `*-v2`) |

### Memory Bank facts that survive v1 → v2

If v1 ever wrote any `human-rejected` facts to its local Memory Bank
backend, those represent operator decisions and should ideally carry
over. Since v1's Memory Bank backend was hand-rolled and in-process
(per `shared/memory.py`), and the v1 deployment never produced a
finished cycle (per chunk 1's "v1 is dead on arrival"), there are
**zero `covered` facts** to port. Any `human-rejected` facts that the
operator set during testing are listed here:

```
[NONE — confirmed via shared/memory.py inspection. v1's
MemoryBankClient.in_memory() resets on process restart, so
no v1 facts persisted to anywhere durable.]
```

If this changes (e.g. operator manually loaded facts via
`memory_bank_add_fact()` calls), document them here before deleting v1.

### v1 GCP resources to delete (post-v2-staging)

| Resource | Delete with |
|---|---|
| Cloud Run service `ai-release-pipeline` (us-east1) | `gcloud run services delete ai-release-pipeline --region=us-east1` |
| Cloud Function `ai-release-pipeline-trigger` | `gcloud functions delete ai-release-pipeline-trigger --gen2 --region=us-east1` |
| Cloud Scheduler `ai-release-pipeline-hourly` (us-east1) | `gcloud scheduler jobs delete ... --location=us-east1` |
| Pub/Sub topic `ai-release-pipeline-trigger` | `gcloud pubsub topics delete ai-release-pipeline-trigger` |
| GCS bucket `gen-lang-client-0366435980-airel-assets` (v1) | `gsutil rm -r gs://...` (after confirming no in-flight references) |
| Service accounts `ai-release-pipeline-fn`, `-sched` | `gcloud iam service-accounts delete ...` |
| Secrets `ai-release-pipeline-github-token`, `-telegram-bot-token` | `gcloud secrets delete ...` (v2 creates new ones with `airel-v2-` prefix) |

**When to do the deletes:** AFTER v2 has run cleanly in staging for at
least one polling cycle (one published article OR one Triage skip).
Until then, v1's resources stay (paused) so we can roll back.

---

## §15 — Open questions, expanded

§15 was a placeholder seeded with 7 (now 8) questions. Each is
reviewed here with current status, default decision, and what would
trigger a revisit.

### Q1 — region for Agent Runtime and Memory Bank

**Status:** RESOLVED — `us-west1` chosen (matches the existing console
deployments per the screenshot in chunk 1).

**Lingering risk:** Memory Bank availability in `us-west1`
not confirmed in this design — verify with `gcloud ai memory-banks
list --region=us-west1` before §10.1's first deploy. If unavailable,
fall back to `us-central1` for Memory Bank only (cross-region cost is
~$0/month at our volume).

### Q2 — provision Memory Bank instance: Terraform or gcloud?

**Status:** OPEN.

**Default:** Provision via `gcloud ai memory-banks create` (one-shot
admin command); then **import into Terraform** as a manual `terraform
import google_ai_memory_bank.airel airel-v2-memory` so future
operations can manage it.

**Why this default:** Terraform's `google_ai_memory_bank` resource
exists but the Memory Bank API is in preview; resource may not have
full feature coverage. gcloud-create-then-import is the standard escape
hatch for this situation.

**Trigger to revisit:** if the Terraform resource gains full
feature coverage by the time v2 ships, switch to fully Terraform-managed.

### Q3 — Cloud Scheduler trigger path

**Status:** RESOLVED in §10.5 — direct HTTP to Vertex `:streamQuery`
endpoint with OIDC auth. No Pub/Sub, no Cloud Function.

**Trigger to revisit:** if Vertex changes the audience contract or
the streamQuery endpoint shape.

### Q4 — duplicate-trigger idempotency

**Status:** RESOLVED conceptually, NEEDS PRODUCTION TEST.

**Default:** The Topic Gate's `interrupt_id = topic-gate-{short_hash(url)}`
is stable across triggers — duplicate Pub/Sub triggers (or duplicate
Cloud Scheduler triggers from manual + cron) on the same release
collide and "join" the same paused session. The second trigger does
NOT race with the first.

**Why this default:** correct behavior when the operator wants idempotent
"latest stuck pause wins" semantics.

**Test required before going live:**
- Fire two triggers within 10s on the same release.
- Assert exactly one Telegram message is posted.
- Assert second trigger's session_id matches the first (the `interrupt_id`
  collision merges them).

If the Vertex SDK or Workflow runtime DOESN'T merge by collision, we
fall back to the simpler "drop the second trigger, log" alternative
(§2 Goal 4).

**Trigger to revisit:** the production test above.

### Q5 — asset bucket lifecycle

**Status:** RESOLVED. **90-day TTL** (same as v1).

**Why:** images and MP4s for published articles are referenced by
Medium-published posts; readers may load them weeks after publish.
90 days is a balance between storage cost and cache-warmness.

**Trigger to revisit:** monthly storage bill review. If costs grow
linearly, drop to 30 days.

### Q6 — Veo model ID

**Status:** OPEN.

**Default in this draft:** `VEO_MODEL` env var, value TBD per first
deploy. v1 default `veo-3.1-fast-generate-preview` 404'd; the working
ID needs to be confirmed via:

```bash
gcloud ai models list --region=us-west1 --filter='displayName~veo'
```

**Trigger to resolve:** before §10.1's first deploy. Update the env
var in `deploy.py`'s `env_vars` map.

### Q7 — Anthropic news scraper

**Status:** RESOLVED. **Keep as HTML scrape** (works, 11/10 live
sources currently passing).

**Trigger to revisit:** if Anthropic ships a public RSS feed
(unlikely given their current site is Next.js-rendered). Migration
would be: drop `poll_anthropic_news` HTML logic; add the URL to
`RSS_FEEDS` dict in `tools/pollers.py`.

### Q8 — ffmpeg in source-based Agent Runtime

**Status:** RESOLVED in this draft. **v2 ships MP4-only** (no GIF /
poster derivation; no ffmpeg dep).

**Trigger to revisit:** if any downstream consumer (a Medium
auto-publisher, a tweet-thread generator, etc.) specifically needs the
GIF or poster. Then we adopt option 1 (`imageio-ffmpeg` wheel) or
option 3 (separate Cloud Run video service).

### Summary — open vs resolved

| # | Question | Status |
|---|---|---|
| Q1 | Region | RESOLVED (us-west1) |
| Q2 | Memory Bank provisioning | DEFERRED — gcloud + import default |
| Q3 | Scheduler trigger path | RESOLVED |
| Q4 | Duplicate-trigger idempotency | RESOLVED CONCEPTUALLY — needs production test |
| Q5 | Asset bucket lifecycle | RESOLVED (90d TTL) |
| Q6 | Veo model ID | OPEN — confirm at first deploy |
| Q7 | Anthropic RSS migration | RESOLVED (keep HTML scrape) |
| Q8 | ffmpeg / video derivation | RESOLVED (MP4-only) |

**5 of 8 fully resolved. 1 deferred (Q2). 1 conceptual + needs test
(Q4). 1 open (Q6 — operational discovery, not a design choice).**

The design is implementable. Implementation can begin against this
document; remaining questions are operational discoveries that get
answered during the first deploy.

---

**Status:** all 8 chunks drafted. §1 through §15 complete.
Implementation can begin against this document.

---

## Appendix A — Why this structure (so we don't argue about it later)

**Why per-node specs as their own subsections (§6.1–6.11)?** Each node is
the smallest unit of behavior an operator needs to reason about during
incidents. If something goes wrong at the Editor, the operator should be
able to read §6.9 in isolation and understand inputs, outputs, side
effects, and failure modes — without needing the rest of the doc.

**Why split Tools (§7) from per-node specs (§6)?** Several nodes call
the same tool (e.g. multiple researchers call `web_fetch`; both Topic
Gate and Editor call Telegram). One tool = one contract. Documenting
each tool once eliminates per-node copies that drift apart.

**Why a separate HITL contract section (§8)?** The two human gates
(Topic Gate and Editor) share the same `RequestInput` mechanic and the
same Telegram bridge. The mechanic is novel enough that it deserves its
own normative section the implementations cite.

**Why "failure modes & recovery" (§12) as a top-level section?** v1
shipped with three production bugs that were not in the design doc
(broken pollers, video_asset early-exit, Veo model 404). Making failure
modes a first-class section of the design forces us to think through
each before writing code, not after deploying.

**Why "what survives v1 → v2" as a top-level section (§14)?** v1 won't
be migrated — it's dead per chunk 1's authoring rules. But the operator
still needs an explicit "delete this, keep that" table so we don't lose
the few items worth porting (the seven pollers, the tools/, the prompts,
the Memory Bank `human-rejected` facts that represent prior operator
decisions). One short table, no rollout phases.

---

## Appendix B — Drafting plan history (how this doc was written)

| Chunk | Sections | When | Notes |
|---|---|---|---|
| 1 | TOC + scope rules | First pass | Confirmed outline before writing detail |
| 2 | §1, §2, §3 | Second pass | Top-level framing — delta table, goals/non-goals, architecture diagram |
| 3 | §4, §5 | Third pass | State schema (`PipelineState`) + canonical `Workflow(edges=[...])` |
| 4a | §6.1, §6.2, §6.3 | Fourth pass | Scout, Triage, Topic Gate (HITL #1) |
| 4b | §6.4, §6.5, §6.6 | Fifth pass | Research, Architect, Writer loop |
| 4c | §6.7, §6.8, §6.9, §6.10, §6.11 | Sixth pass | Assets, Repo, Editor (HITL #2), Revision, Publisher |
| 5 | §7.1–§7.9 | Seventh pass | Tools — port + adapt + new |
| 6 | §8, §9 | Eighth pass | HITL contract, Memory Bank schema |
| 7 | §10, §11 | Ninth pass | Deployment, Observability |
| 8 | §12, §13, §14, §15 | Tenth pass | Failure modes, Eval, What survives, Open questions |

**Drafting protocol followed.** After each chunk landed, the operator
either said "next" (continue to the next chunk) or "fix X first"
(revise this chunk before continuing). The protocol prevented late-stage
inconsistencies — when chunk 4c surfaced that `video_asset_agent` should
become a function node, §5 was updated retroactively in the same edit
rather than left as a stale reference.

**Total length of final draft.** ~5800 lines, ~80 pages of
markdown. Written across 8 chunks with explicit handshakes.
