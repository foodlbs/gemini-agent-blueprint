# Spec — Public Launch of `gemini-agent-blueprint`

Date: 2026-05-01
Status: Draft → ready for implementation plan
Goal: Take the existing private repo (`Content Gemini Agent`), prepare it
for public release as `gemini-agent-blueprint`, write a Medium article + tweet
thread + LinkedIn post that frame the build-in-public narrative.

---

## 1. Context & Decisions Locked

This spec consolidates a brainstorming session held on 2026-05-01.
Five top-level decisions, captured here so the implementation plan
inherits them without re-litigation:

| # | Decision | Choice |
|---|---|---|
| 1 | Goal of going public | **Building in public** — repo + article feed each other for brand-building / discoverability. Not chasing OSS maintenance, not a portfolio one-shot. |
| 2 | Repo philosophy | **Lean code artifact + ONE polished `docs/ARCHITECTURE.md`** (mix of "lean" and "curated story" options). Article carries the narrative; repo carries the working thing + an authoritative deep-dive doc. |
| 3 | Deployability target | **Genuinely fork-friendly** — anyone with GCP + Telegram + GitHub + Medium can deploy. Light parameterization (~1-2 hours of refactor work) so all `airel-v2-*` hardcoded references become driven by `var.project_name`. |
| 4 | Public repo name | `gemini-agent-blueprint` |
| 5 | Article + social package | **Medium long-form (~2,300 words)** with hybrid structure (story hook + 5 numbered lessons), plus a **5-tweet thread** (curated to 3 lessons + hook + CTA), plus a **standalone LinkedIn post** (different voice — paragraph-led, all 5 lessons listed, single CTA). |

---

## 2. Goals & Non-Goals

### Goals

- Working `git clone` → `uv sync` → `local_run.py` flow from a fresh checkout
- Working full deploy via terraform + `deploy.py` for someone with the prereqs
- Polished public README that converts visitors → article readers and forkers
- Polished `docs/ARCHITECTURE.md` (~7,500 words) distilled from internal `DESIGN.v2.md`
- Medium article (~2,300 words) ready to publish, with hook + 5 lessons + CTA
- Tweet thread (5 tweets, copy-paste ready) and LinkedIn post (1 post, ~1,500 chars)
- Pre-publish checklist that catches secret leakage before `git push public`
- All `airel-v2-*` / `ai-release-pipeline-v2` / `ai_release_pipeline_v2` references
  parameterized via `var.project_name` (terraform) and env vars (`PROJECT_DISPLAY_NAME`,
  `PROJECT_APP_NAME`)

### Non-Goals

- NOT abstracting the AI-release-pipeline domain into a generic content-agent framework
  (rejected option C — too much effort, dilutes the story)
- NOT prompting templating with a single TOPIC variable (rejected option B — leaky abstraction)
- NOT accepting issues/PRs as a maintained OSS project (set expectations: this is a reference)
- NOT writing follow-up articles on a sustained schedule (rejected option D from article-format question — single drop)
- NOT cross-posting to dev.to / Hashnode in the launch sequence (optional follow-up only)

---

## 3. Section 1 — Repo Structure & Parameterization

### 3.1 Final repo structure

```
gemini-agent-blueprint/
├── README.md                       NEW — public-facing entry point
├── LICENSE                         NEW — MIT
├── .env.example                    KEEP — already clean
├── .gitignore                      KEEP
├── pyproject.toml                  KEEP — version reset to 0.1.0, name → gemini-agent-blueprint
├── uv.lock                         KEEP
├── agent.py                        KEEP (parameterized — see 3.3)
├── local_run.py                    KEEP — labeled as "dev driver" in README
├── deploy.py                       KEEP — parameterized
│
├── agents/                         KEEP — all 7 LlmAgent files
├── nodes/                          KEEP — all 12 function-node files
├── tools/                          KEEP — all 11 tool files
├── shared/                         KEEP — models, prompts, markdown_assets
├── telegram_bridge/                KEEP — Cloud Run bridge service
├── tests/                          KEEP — entire pytest suite
│
├── deploy/
│   └── terraform/                  RENAMED from deploy/v2/
│       ├── README.md               KEEP — operator runbook (lightly edited for parameterization)
│       └── *.tf                    KEEP — parameterized via TF_VAR_project_name
│       (terraform.tfstate, .terraform/, tfplan stay gitignored — not in tree)
│
└── docs/
    └── ARCHITECTURE.md             NEW — distilled from DESIGN.v2.md
```

### 3.2 Files to delete

| Path | Why |
|---|---|
| `spike/` (4 scripts + results.md) | Story material migrates into the article |
| `sample/*.jpg` (3.4 MB tracked screenshots) | Personal Telegram screenshots; one redacted version goes to `docs/img/hitl-telegram.png` |
| `DESIGN.v2.md` (268 KB internal contract doc) | Replaced by `docs/ARCHITECTURE.md` |
| `docs/superpowers/specs/` (this directory) | Internal brainstorming history |
| `docs/superpowers/plans/` | Internal implementation plans |
| `deploy/v2/tfplan` | Stale binary terraform plan |

### 3.3 Parameterization plan

Single source of truth: a terraform variable `var.project_name` (default `"gab"`)
drives all derived resource names. Forkers set `TF_VAR_project_name=myagent` and
`terraform apply` provisions resources prefixed `myagent-*`.

| Today (hardcoded) | Becomes | Default |
|---|---|---|
| `"ai-release-pipeline-v2"` (display name) | env `PROJECT_DISPLAY_NAME` | `"gemini-agent-blueprint"` |
| `"ai_release_pipeline_v2"` (app_name) | env `PROJECT_APP_NAME` | `"gemini_agent_blueprint"` |
| `"airel-v2-app"` (SA name) | `"${var.project_name}-app"` (TF) | `"gab-app"` |
| `"airel-v2-github-token"` (secret) | `"${var.project_name}-github-token"` | `"gab-github-token"` |
| `"airel-v2-telegram-bot-token"` | `"${var.project_name}-telegram-bot-token"` | `"gab-telegram-bot-token"` |
| `"airel-v2-telegram-webhook-secret"` | `"${var.project_name}-telegram-webhook-secret"` | `"gab-telegram-webhook-secret"` |
| `"airel-v2-staging"` (bucket) | `"${project}-${var.project_name}-staging"` | `"${project}-gab-staging"` |
| `"airel-assets-v2"` (bucket suffix) | `"${project}-${var.project_name}-assets"` | `"${project}-gab-assets"` |
| `GITHUB_ORG = "pixelcanon"` (default) | required env (no default) | — |
| `TELEGRAM_APPROVAL_CHAT_ID = "8481672863"` (default) | required env (no default) | — |
| `REGION = "us-west1"` | env-overridable, default kept | `us-west1` |

Files touched by parameterization:
- `deploy.py` — read env, compute names, no hardcoded defaults for sensitive values
- `deploy/terraform/main.tf` — `var.project_name`, derived resource names
- `deploy/terraform/iam.tf` — derived SA names + secret names
- `deploy/terraform/outputs.tf` — output the derived names so deploy.py can consume
- `deploy/terraform/README.md` — runbook updated to reference `var.project_name`
- `agent.py` — `Workflow(name=...)` reads from env

### 3.4 Pre-publish checklist (`docs/PRE_PUBLISH_CHECKLIST.md`)

Throw-away file. Tick before `git push public main`, then delete.

```
- [ ] Rotate GitHub PAT (current one is in local .env)
- [ ] Rotate Telegram bot token (current one is in local .env)
- [ ] Verify .env not in git history: `git log --all -- .env` returns nothing
- [ ] Verify no real GCP project IDs in code/docs: `grep -r "gen-lang-client-" .`
- [ ] Verify no real chat IDs: `grep -r "8481672863" .`
- [ ] Verify no real org names in code: `grep -r "pixelcanon" . --exclude-dir=.git`
      (only acceptable hit: nowhere — the previous default has been removed)
- [ ] Verify .env.example covers every env var that deploy.py / terraform reads
- [ ] Run `uv run pytest` — full suite green
- [ ] Run `uv run python local_run.py` — completes through to first HITL pause
- [ ] Run `cd deploy/terraform && terraform plan -var=project_name=test` — plan succeeds
```

---

## 4. Section 2 — README.md Structure

**Target length:** ~600-700 lines. **Audience priority:** article-arriving visitor (60%) > deploy-attempting forker (30%) > skim-and-leave (10%).

### 4.1 Section list

1. **Title + 1-line tagline + badges** (~10 lines)
2. **Hero block** (~30 lines) — Mermaid 5-phase flowchart + one redacted Telegram screenshot
3. **Why this exists** (~80 lines) — v1 problem, ADK 2.0 solution, link to article ("Read the full story →")
4. **What's inside** (~60 lines) — capability bullets + tech stack table
5. **Architecture overview** (~80 lines) — 5-phase summary + link to ARCHITECTURE.md + key patterns called out
6. **Quick start — local exercise** (~50 lines) — prereqs, 4 steps, expected output
7. **Full deployment** (~100 lines) — phased link-out to deploy/terraform/README.md
8. **Forking for your own topic** (~80 lines) — the differentiator section, lists 4 files to edit
9. **Project structure** (~40 lines) — top-level dir tree with one-liner descriptions
10. **Testing** (~20 lines) — `uv run pytest`, smoke test mention
11. **Roadmap / known limitations** (~30 lines) — Beta SDK warning, "reference not product" disclaimer
12. **Read the story / Connect** (~30 lines) — Medium + Twitter + LinkedIn + GitHub links
13. **License + Acknowledgements** (~20 lines) — MIT + Built-on credits

### 4.2 Inline assets

- **Mermaid 5-phase flowchart** (Section 2 hero) — renders inline on GitHub natively
- **Redacted Telegram screenshot** at `docs/img/hitl-telegram.png` (Section 2 hero):
  - Source: pick one of the 3 in `sample/`
  - Redaction: black-box chat name, profile, sender info; crop tightly to the prompt + buttons

### 4.3 Conversion CTAs (deliberate redundancy)

Three hits to the article URL:
1. End of "Why this exists" — "Read the full story →"
2. End of "Forking for your own topic" — "More on the design tradeoffs in the article →"
3. Section 12 footer — "Read the story / Connect"

### 4.4 "Forking for your own topic" — the 4-file swap

The README's differentiator section explicitly enumerates:

1. `tools/pollers.py` — swap source-fetching functions for your domain
2. `shared/prompts.py` — rewrite the 11 LlmAgent instruction prompts
3. `agents/scout.py` — adjust scout's source list
4. `agents/repo_builder.py` — toggle off if not generating example code

Plus: rename via `TF_VAR_project_name`, set `PROJECT_DISPLAY_NAME` and `PROJECT_APP_NAME` env vars.

Examples listed: research-paper digest, security advisory tracker, sports-news bot.

---

## 5. Section 3 — `docs/ARCHITECTURE.md` Structure

**Source:** `DESIGN.v2.md` (268 KB) → distilled to ~35-40 KB / ~7,500 words. **Audience:** engineer who has read README, wants the deep-dive. **Tone:** authoritative + honest about tradeoffs.

### 5.1 Section list

1. **Overview & problem statement** (~400 words)
2. **The workflow graph** (~800 words) — full Mermaid flowchart, dict-edge routing, fan-out tuple, JoinFunctionNode
3. **State schema** (~400 words) — PipelineState (Pydantic), dict-vs-model rehydration gotcha
4. **Per-phase walkthrough** (~2,500 words across 5 subsections):
   - 4.1 Phase 1 — Polling, Scout, Triage (~500)
   - 4.2 Phase 2 — Topic Gate (HITL #1) (~500) ★
   - 4.3 Phase 3 — Research → Architect → Writer loop (~500)
   - 4.4 Phase 4 — Asset chain + Repo (~500) ★ war story
   - 4.5 Phase 5 — Editor (HITL #2) + Publish (~500)
5. **HITL contract — the protocol** (~1,000 words) ★ standalone-worthy, includes Mermaid `sequenceDiagram`
6. **Memory Bank wiring** (~400 words)
7. **Deployment shape** (~400 words) — pointer to `deploy/terraform/README.md` for full steps
8. **Observability** (~250 words)
9. **Failure modes & recovery** (~600 words)
10. **Lessons learned** (~600 words) — terse reference version; full narrative in article. Each lesson links to the article for the story.
11. **Further reading** (~150 words)

### 5.2 What gets dropped from `DESIGN.v2.md`

- All `[TBD]` markers and unfilled sections
- Chunk-reference annotations (`[DRAFTED — chunk 4a]`, etc.)
- Internal section numbering (v2.6.1 etc.)
- Per-node contract specs (lives in code, not useful publicly)
- v1 deltas / migration notes
- Section 15 (open questions)

### 5.3 What gets added

- The Mermaid `sequenceDiagram` for HITL (new — DESIGN.v2.md has no sequence diagram)
- The "Lessons learned" reference section (new — distilled for engineers)
- "★ ARCHITECTURALLY INTERESTING" call-out headers for the 2-3 sections worth lingering on

### 5.4 Naming consistency

All references to specific GCP project IDs / chat IDs / GitHub orgs replaced
with `<project-id>`, `<chat-id>`, `<github-org>` placeholders. All `airel-v2-*`
references use the parameterized prefix.

---

## 6. Section 4 — Medium Article Structure

**Title (working):** *"My AI agent deployed cleanly and never wrote a single article. Here's what I learned rebuilding it on Google's Gemini Agent Platform."*

**Subtitle:** *"Five engineering lessons from shipping a production graph workflow with 24-hour human-in-the-loop on ADK 2.0."*

**Length:** ~2,300 words. **Reading time displayed:** ~10 min. **Tags:** Google Cloud, Gemini, AI Agents, Vertex AI, Software Engineering.

### 6.1 Section list with word allocation

1. **Hook** (~180 words) — concrete failure story: "Deployed cleanly, three weeks, zero articles." End with repo CTA in the last sentence.
2. **Context** (~250 words) — what the agent does, why the combination is hard, embed Mermaid 5-phase diagram
3. **Lesson 1 — 24h HITL is incompatible with serverless request models** (~350 words) — embed sequence diagram from ARCHITECTURE.md §5
4. **Lesson 2 — Spike before committing to a Beta SDK** (~350 words) — embed table from `spike/results.md` (the file gets deleted but its content lives in the article)
5. **Lesson 3 — Make the LLM produce text, not data** (~350 words)
6. **Lesson 4 — Don't put binary blobs in your LLM's tool history** (~350 words) ★ cleanest war story; embed before/after code excerpt
7. **Lesson 5 — Fan-out tuples don't barrier; build a JoinFunctionNode** (~350 words) — embed `JoinFunctionNode` skeleton code excerpt
8. **Closing** (~200 words) — what's in the repo, what's not, build-in-public note, follow links
9. **About + tags + footer** (~50 words) — 1-2 sentence bio (full-stack developer focused on AI/LLM applications, primary languages Python + TypeScript), repo link as sticky CTA, Twitter + LinkedIn handles

### 6.2 Hook draft (the actual prose)

> On April 15, 2026, I deployed v1 of an AI agent designed to find new AI releases, write articles about them, and post them to Medium. It deployed cleanly. The Cloud Scheduler triggered hourly. Cloud Run responded with HTTP 200. Logs streamed normally.
>
> In three weeks of running, it produced exactly zero articles.
>
> The reason wasn't a bug in the agent's reasoning, the prompts, or the LLM. It was an architectural mismatch I hadn't seen until production made it visible: the agent had two human-approval gates, and humans on Telegram take up to 24 hours to tap a button. Cloud Run requests max out at 60 minutes. Every cycle hit the timeout, lost its state, and the user (me, on my phone) was left tapping Approve into the void.
>
> Here are five lessons from rebuilding it on Google's Gemini Agent Platform — what worked, what blew up at runtime, and what the design looks like at the end. The full code is at github.com/<you>/gemini-agent-blueprint.

### 6.3 Inline assets

| Where | Asset | Source |
|---|---|---|
| Section 2 | 5-phase Mermaid flowchart | Same as README hero |
| Lesson 1 | HITL `sequenceDiagram` | ARCHITECTURE.md §5 |
| Lesson 2 | Spike results grid (text table) | `spike/results.md` |
| Lesson 4 | Code excerpt: before/after of `image_asset` | Pulled from agent code |
| Lesson 5 | Code excerpt: `JoinFunctionNode` skeleton | `nodes/_join_node.py` |

### 6.4 CTAs to repo (3 deliberate hits)

1. End of Hook
2. End of Lesson 4 (peak engagement)
3. Closing

### 6.5 Tone notes for the writing pass

- First-person throughout
- No "we" unless referring to a team (this is solo work)
- Code snippets sparingly — 3-4 max, each <15 lines, syntax-highlighted
- No hedging language ("perhaps", "might be", "could be argued")
- One self-deprecating moment per lesson — keeps the tone honest

---

## 7. Section 5 — Tweet Thread + LinkedIn Post

### 7.1 Tweet thread (5 tweets, ~280 chars each)

**Strategy:** Hook + 3 punchy lessons (curated for shareability) + CTA. The 2 unused lessons live in the article.

| # | Beat | Content |
|---|---|---|
| 1 | Hook | Deployed cleanly, scheduler triggered, 3 weeks → 0 articles. "Here's what I learned rebuilding it 🧵" |
| 2 | Lesson 1 (architectural insight) | 24h HITL ≠ serverless. RequestInput is a suspended generator, not an HTTP wait. |
| 3 | Lesson 4 (war story) | Image bytes in LLM tool history blew the 1M-token cap. Function node, not LlmAgent. |
| 4 | Lesson 5 (concrete technical) | ADK 2.0 tuple fan-out is fan-out only. JoinFunctionNode is counter-gated. |
| 5 | CTA | "Two more lessons in the article" + Medium link + repo link |

Full prose drafts of all 5 tweets live in `docs/launch/tweet-thread.md` (created during implementation).

### 7.2 LinkedIn post (single standalone post, ~1,500 characters)

**Strategy:** Different voice from Twitter — paragraph-led, measured, all 5 lessons listed (LinkedIn rewards thoroughness). One CTA at the bottom + hashtags.

**Format:**
- Hook paragraph (3-4 sentences)
- "Five lessons I learned:" intro line
- 5 single-paragraph lessons (each starts with `→`)
- Closing CTA paragraph (Medium link + repo link)
- Hashtags: `#AI #GoogleCloud #GeminiAI #VertexAI #SoftwareEngineering #BuildInPublic`

Full prose draft lives in `docs/launch/linkedin-post.md`.

### 7.3 Posting cadence

| Time | Channel | Content |
|---|---|---|
| T+0 | Medium | Article published |
| T+5 min | Twitter | 5-tweet thread |
| T+30 min | LinkedIn | Standalone post |

### 7.4 Throwaway launch directory

```
docs/launch/
├── article.md           — full Medium article (paste into Medium editor)
├── tweet-thread.md      — 5 tweets, copy-paste ready
├── linkedin-post.md     — single post, copy-paste ready
└── posting-checklist.md — cadence as a tickable checklist
```

After publishing all three, `docs/launch/` is deleted and replaced with a small
`docs/PRESS.md` containing the published links (Medium URL, Twitter thread URL,
LinkedIn post URL) — a "where to find me" for repo visitors.

---

## 8. Out of Scope (Explicit)

- Demo GIF / screencast for README — too much effort; we ship with Mermaid + 1 screenshot
- Cross-posting to dev.to / Hashnode — optional follow-up only
- Maintaining the repo as accepting OSS issues / PRs — README will set this expectation honestly
- Generic "any topic" content-agent framework — we are NOT abstracting the AI-release domain
- Follow-up article series — single drop, no committed cadence

---

## 9. Implementation Order

The implementation plan should sequence work as follows. Earlier steps are
prerequisites for later ones; each sub-step ends with a verifiable checkpoint.

1. **Parameterization refactor** — terraform vars + env vars + deploy.py, all
   `airel-v2-*` references swapped. Checkpoint: `terraform plan -var=project_name=test` succeeds; `pytest` green.
2. **Deletions + relocations** — `spike/`, `sample/`, `DESIGN.v2.md`, `docs/superpowers/`,
   `deploy/v2/tfplan`, rename `deploy/v2/` → `deploy/terraform/`. Redact one Telegram
   screenshot to `docs/img/hitl-telegram.png`. Checkpoint: `git status` shows the planned diff.
3. **`docs/ARCHITECTURE.md`** — write from scratch using DESIGN.v2.md as raw material.
   Checkpoint: standalone-readable, ~7,500 words, includes both Mermaid diagrams.
4. **`README.md`** — write per Section 2 spec. Includes hero diagram, screenshot embed,
   3 article CTAs (placeholders for the article URL until we publish), Forking section.
   Checkpoint: someone unfamiliar with the project can read top-to-bottom and understand
   it without opening any other file.
5. **`LICENSE`** — MIT, year 2026, copyright holder = `git config user.name` (Rahul Patel).
6. **`docs/PRE_PUBLISH_CHECKLIST.md`** — the 10-item checklist from §3.4. Throwaway.
7. **`docs/launch/article.md`** — write the Medium article per Section 4 spec.
   Checkpoint: ~2,300 words, hook + 5 lessons + closing + footer, all inline assets present.
8. **`docs/launch/tweet-thread.md`** — copy-paste ready 5 tweets per §7.1.
9. **`docs/launch/linkedin-post.md`** — copy-paste ready post per §7.2.
10. **`docs/launch/posting-checklist.md`** — cadence as a tickable list.
11. **Pre-publish dry-run** — tick through `docs/PRE_PUBLISH_CHECKLIST.md`. Rotate any
    secrets. Verify clean greps for project IDs / chat IDs / org names. Run pytest. Run local_run.py.
12. **Public push** — create `gemini-agent-blueprint` repo on GitHub under your account,
    push the cleaned tree, verify README + ARCHITECTURE.md render correctly on GitHub.
13. **Article + thread + LinkedIn** — publish per §7.3 cadence. Fill in the actual
    Medium URL into the README's CTA placeholders. Commit + push that update.
14. **Cleanup of throwaways** — delete `docs/launch/` (after publishing), delete
    `docs/PRE_PUBLISH_CHECKLIST.md` (after publishing), delete `docs/superpowers/`
    (after the implementation plan is no longer needed). Replace with `docs/PRESS.md`
    containing the three published URLs.

---

## 10. Risks & Open Questions

- **ADK 2.0 Beta drift**: `google-adk==2.0.0b1` is the pin. If a 2.0.0b2 ships
  before launch with breaking changes, the article should still be honest about the
  pin. No mitigation needed — this is part of the build-in-public story.
- **Mermaid rendering on Medium**: GitHub renders Mermaid natively; Medium does not.
  For the article, Mermaid diagrams must be exported as PNGs (Mermaid Live Editor →
  PNG) and embedded as images. Add this to the implementation plan as a sub-step
  of step 7.
- **Telegram screenshot redaction**: requires manual image editing. Easiest tool:
  Preview on macOS (rectangular crop + black-rectangle markup). Acceptable to
  document the redaction steps in the implementation plan.
- **Article URL chicken-and-egg**: the README has 3 CTAs to the Medium article URL,
  but the URL doesn't exist until the article is published. Implementation plan
  uses a `<MEDIUM_URL>` placeholder, then a step 13 substep replaces it after
  publish.
