# DESIGN.md — AI Release → Article + Assets + Repo multi-agent system

A polling, multi-agent content pipeline built on Google's **Gemini Enterprise Agent Platform** (the rebranded Vertex AI, GA April 2026), with **Gemini** models across every agent. Two human-in-the-loop checkpoints bookend the LLM-heavy work: a **Topic Gate** before research begins (so you only pay for content you'd publish), and a **Revision Loop** after the final draft (so you can request changes, not just approve or reject).

> **Changes from v1.1:** added the Topic Gate (agent #3) for human topic approval before the Researcher pool runs; restructured the Editor as part of a Revision Loop (agents #9 and #10) that supports a 3-way verdict (approve/reject/revise-with-feedback) and iterates up to 3 times. The Revision Writer is a new agent that incorporates human feedback and rewrites the draft. Pipeline is now 10 agents.

## TL;DR

- **Ten small agents** orchestrated as a `SequentialAgent` with five nested orchestration patterns: a `ParallelAgent` for research fan-out, a `LoopAgent` for the drafter↔critic revision cycle, a `ParallelAgent` for the post-writer block (Asset Agent + Repo Router), and a final `LoopAgent` for the human revision loop (Editor + Revision Writer).
- **Two human gates:**
  - **Topic Gate** posts the chosen release to Telegram with rationale and waits for Approve / Skip. Skip ends the run gracefully and writes the rejection to Memory Bank so it doesn't re-surface.
  - **Revision Loop** posts the final draft with assets to Telegram for Approve / Reject / Revise-with-feedback. On Revise, the human types feedback as a Telegram reply, the Revision Writer rewrites the draft, and the Editor re-presents. Max 3 iterations.
- **Gemini across the board:** 3.1 Flash for cheap classification (Scout, Triage, Topic Gate, Researchers, Asset sub-agent orchestration, Repo Router), 3.1 Pro for reasoning (Architect, Drafter, Critic, Repo Builder, Editor, Revision Writer), Nano Banana 2 for image generation, Veo 3.1 Fast for video.
- **Memory Bank** is the deduplication brain — every shipped article writes a fact ("covered: X on date"), and every human-skipped topic writes a "human-rejected" fact, both filtered by Triage on the next run.
- **Conditional repo and conditional video creation** (`needs_repo`, `needs_video` flags from Architect). Image generation always runs.
- **Asset hosting:** Cloud Storage bucket with public-read access, 90-day lifecycle. Video gets converted to GIF for Medium-friendly inline embed; the full MP4 is retained for the GitHub repo's `assets/` folder.
- **Trigger:** Cloud Scheduler hits a Cloud Function hourly. Sessions are isolated, so multiple pending pipelines (waiting at Topic Gates or Revision Loops) can queue without interfering.
- **Cost target:** ~$30-40/month at hourly polling and ~10-15 articles/month with conditional video. See dial-down options.

## The ten agents at a glance

| # | Agent | Model | Type | Reads from state | Writes to state |
|---|-------|-------|------|------------------|-----------------|
| 1 | Scout | Gemini 3.1 Flash | LlmAgent | — | `candidates` |
| 2 | Triage | Gemini 3.1 Flash | LlmAgent | `candidates` | `chosen_release` |
| 3 | Topic Gate | Gemini 3.1 Flash | LlmAgent (human gate) | `chosen_release` | `topic_verdict` (and on skip, sets `chosen_release = None`) |
| 4 | Researcher pool | Gemini 3.1 Flash | ParallelAgent | `chosen_release` | `docs_research`, `github_research`, `context_research` |
| 5 | Architect | Gemini 3.1 Pro | LlmAgent | `chosen_release`, `*_research` | `outline`, `article_type`, `needs_repo`, `needs_video`, `image_brief`, `video_brief` |
| 6 | Writer | Gemini 3.1 Pro | LoopAgent | `outline`, `*_research` | `draft` |
| 7 | Asset Agent | Flash + media models | ParallelAgent | `image_brief`, `video_brief`, `needs_video` | `image_assets`, `video_asset` |
| 8 | Repo Builder | Gemini 3.1 Pro | LlmAgent (conditional) | `chosen_release`, `outline`, `image_assets` | `repo_url` |
| 9 | Editor | Gemini 3.1 Pro | LlmAgent (in revision loop) | everything above, `human_feedback` | `final_article`, `editor_verdict`, `human_feedback`, `medium_draft_url` |
| 10 | Revision Writer | Gemini 3.1 Pro | LlmAgent (in revision loop) | `draft`, `editor_verdict`, `human_feedback` | `draft` (rewritten) |

The session state object is the contract between agents. Treat it like a typed dict — every agent's instruction explicitly names the keys it reads and writes.

## Detailed agent specs

### 1. Scout

**Role:** Poll a configured list of feeds and APIs, return a structured list of candidate releases from the last polling window.

**Tools:** `poll_arxiv`, `poll_github_trending`, `poll_rss`, `poll_hf_models`.

**Instruction prompt:**

> You are Scout, the first agent in an AI-news content pipeline. Gather candidate releases from the last polling window and return them as structured JSON. Do not editorialize, do not score importance.
>
> 1. Call all four polling tools with `since` = `state["last_run_at"]` (or 24h ago if missing).
> 2. Combine into one flat list. Each item: `title, url, source, published_at, raw_summary` (source ∈ {arxiv, github, anthropic, google, openai, huggingface, other}).
> 3. Drop obvious non-releases — job postings, marketing fluff, conference recaps without a paper link.
> 4. Cap at 25 items, preferring anthropic/google/openai when capped.
>
> Output: write to `state["candidates"]`.

### 2. Triage

**Role:** Score each candidate's significance, deduplicate against Memory Bank, pick exactly one winner (or none).

**Tools:** `memory_bank_search`.

**Instruction prompt:**

> You are Triage. Pick **exactly one** candidate from `state["candidates"]` to write about, or pick **none**.
>
> For each candidate:
> 1. **Significance** (0-100): named major lab (+40), new artifact not minor update (+20), introduces capability/SDK/protocol (+20), has working code or docs available now (+20).
> 2. **Novelty:** call `memory_bank_search` with title and 3-word summary. If similarity > 0.85, drop as duplicate. Pay special attention to facts tagged `human-rejected` from prior Topic Gate skips — those are hard rejects.
> 3. **Threshold:** score ≥ 70 AND novelty clear.
>
> If exactly one clears, write to `state["chosen_release"]` with `score`, `rationale`, and `top_alternatives` (next 2 highest-scoring candidates that also passed novelty, for the Topic Gate to optionally surface). If multiple clear, pick highest score, ties broken by recency. If none clear, write `state["chosen_release"] = None` and `state["skip_reason"]`.

### 3. Topic Gate (human approval)

**Role:** Post the chosen topic to Telegram with the Triage rationale and wait for Approve / Skip. On Approve, the pipeline continues. On Skip, the topic is recorded as human-rejected in Memory Bank and the run ends gracefully.

**Why a separate agent:** Triage's job is decision logic; the human gate is a different concern (interaction). Keeping them separate means you can swap channels (Telegram → Slack → email) without touching Triage, and you can disable the gate during testing by removing one line from the orchestrator.

**Model:** Gemini 3.1 Flash — orchestration only, the actual decision is human.

**Tools:**
- `telegram_post_topic_for_approval(chosen_release, rationale, top_alternatives) -> TopicVerdict` — posts to Telegram with Approve / Skip inline buttons. Returns `{verdict: "approve" | "skip", at: ISO8601}`. 24-hour timeout.
- `memory_bank_add_fact(scope, fact, metadata)` — used to record human rejections.

**Instruction prompt:**

> You are the Topic Gate, a human-approval checkpoint. You will not make any decisions yourself — you simply present the chosen topic and capture the human's verdict.
>
> If `state["chosen_release"]` is None, end your turn immediately without using tools (Triage already decided to skip).
>
> Otherwise:
> 1. Call `telegram_post_topic_for_approval` with `chosen_release`, the rationale, and `top_alternatives` from Triage. The tool will block until the human responds (max 24 hours).
> 2. Parse the returned verdict.
> 3. If verdict is `"approve"`: write `state["topic_verdict"] = "approve"` and end your turn. The pipeline continues to research.
> 4. If verdict is `"skip"`: call `memory_bank_add_fact` with `fact = "Human rejected topic: <title>"`, metadata including the URL, source, and timestamp, and `scope = "ai_release_pipeline"`. Then set `state["chosen_release"] = None` and `state["skip_reason"] = "human-rejected"`. End your turn — downstream agents will see `chosen_release` is None and exit.
> 5. If the tool times out (no response in 24h): treat as `skip` for safety — set `chosen_release = None`, `skip_reason = "topic-gate-timeout"`, but do NOT add to Memory Bank (the topic might still be worth covering on a later cycle).

**Output schema:** `state["topic_verdict"]` is `"approve"`, `"skip"`, or `"timeout"`. On non-approve outcomes, `state["chosen_release"]` is set to None.

### 4. Researcher (Parallel)

(Same as v1.1 — three sub-agents fan out for docs, GitHub, and context. First instruction line of each: "If `state['chosen_release']` is None, end your turn immediately.")

#### 4a. Docs researcher
Gemini 3.1 Flash. Tools: `web_fetch`, `google_search`. Writes `state["docs_research"]` as `{summary, headline_quotes (≤2, ≤14 words each), code_example, prerequisites}`.

#### 4b. GitHub researcher
Gemini 3.1 Flash. Tools: `github_get_repo`, `github_get_readme`, `github_list_files`. Writes `state["github_research"]`.

#### 4c. Context researcher
Gemini 3.1 Flash. Tool: `google_search`. Finds 3-5 reactions/comparisons/related releases from last 30 days. Paraphrases — never quotes. Writes `state["context_research"]`.

### 5. Architect

**Role:** Decide the article shape, produce a detailed outline, and produce briefs for both the Asset Agent and the Repo Builder.

**Model:** Gemini 3.1 Pro. **Tools:** None.

**Instruction prompt:**

> You are the Architect. From `state["chosen_release"]`, `state["docs_research"]`, `state["github_research"]`, `state["context_research"]`, decide:
>
> 1. **Article type:** `quickstart` | `explainer` | `comparison` | `release_recap`. Default to `quickstart` if there's runnable code in `github_research`.
>
> 2. **Outline** — section-by-section, each with heading, one-sentence intent, key research items it draws from, estimated word count. Total: 1200-1800 for quickstart, 800-1200 otherwise.
>
> 3. **needs_repo:** True only if (a) quickstart, (b) official sample is non-trivial to set up, (c) a curated starter would meaningfully accelerate the reader.
>
> 4. **image_brief:** 3-4 image specs. Always one cover (16:9). 1-2 inline (4:3 or 16:9) for visual moments. Each: `{position, description (the actual prompt), style, aspect_ratio}`. Styles ∈ {photoreal, diagram, illustration, screenshot}. Positions ∈ {cover, after-section-1, after-section-2, ...}.
>
> 5. **needs_video and video_brief:** True only if (a) quickstart, (b) reader benefit from motion is high, (c) compelling enough to justify ~$2-3 of compute. If True: `video_brief = {description, style, duration_seconds (4-8), aspect_ratio "16:9"}`. Be conservative.
>
> 6. **Title and subtitle** — working only.
>
> Output: `state["outline"]`, `state["article_type"]`, `state["needs_repo"]`, `state["image_brief"]`, `state["video_brief"]`, `state["needs_video"]`, `state["working_title"]`, `state["working_subtitle"]`.

### 6. Writer (Loop)

#### 6a. Drafter
Gemini 3.1 Pro. No tools. Writes article markdown following outline exactly. Quote any source ≤14 words and at most once. Inserts `<!-- IMAGE: <position> -->` and `<!-- VIDEO: hero -->` placeholders matching the briefs. Writes `state["draft"]`.

#### 6b. Critic
Gemini 3.1 Pro. Tool: ADK Code Execution. Scores 5 axes (1-5 each): accuracy, code-correctness, originality, copyright safety, reader value. Verifies image/video markers present. If total < 22 or any axis < 4, writes feedback to `state["critic_feedback"]` and `state["critic_verdict"] = "revise"`. Otherwise sets `"accept"` and calls `tool_context.actions.escalate = True`.

`LoopAgent(max_iterations=3, sub_agents=[drafter, critic])`.

### 7. Asset Agent (Parallel)

(Same as v1.1.)

#### 7a. Image Asset Agent
Gemini 3.1 Flash. Tools: `generate_image` (Nano Banana 2), `upload_to_gcs`. Iterates through `state["image_brief"]`, generates each image, uploads, builds alt_text. Writes `state["image_assets"]`.

#### 7b. Video Asset Agent
Gemini 3.1 Flash. Tools: `generate_video` (Veo 3.1 Fast, capped at 8s), `convert_to_gif`, `extract_first_frame`, `upload_to_gcs`. First instruction line: "If `state['needs_video']` is False or `state['video_brief']` is None, end your turn immediately." Generates MP4, converts to GIF, extracts JPEG poster, uploads all three. Writes `state["video_asset"]`.

### 8. Repo Builder (conditional)

(Same as v1.1.)

Wrapped in a `repo_router` LlmAgent on Gemini 3.1 Flash that transfers control only if `state["needs_repo"]` is True. The Repo Builder runs on Gemini 3.1 Pro and uses `github_create_repo`, `github_commit_files`, `github_set_topics`. Commits the asset bundle (cover.png, tutorial.mp4, tutorial-poster.jpg) to `assets/` if available. Writes `state["repo_url"]` or sets it to None with `state["repo_skip_reason"]`.

### 9. Editor (in revision loop)

**Role:** Final QA, weave assets, post to human, capture verdict. The Editor is now the entry point of a Revision Loop — its verdict drives whether the loop continues or exits.

**Model:** Gemini 3.1 Pro.

**Tools:**
- `medium_format(markdown)`
- `telegram_post_for_approval(article, repo_url, asset_summary) -> EditorVerdict` — posts with **three** inline buttons: Approve, Reject, Revise. On Revise tap, sends a `ForceReply` prompt asking for feedback text and waits for the next message in chat. Returns `{verdict: "approve" | "reject" | "revise", feedback: str | None, at: ISO8601}`. 24-hour timeout per round.
- `memory_bank_add_fact(scope, fact, metadata)` — used after Approve to record successful coverage.

**Instruction prompt:**

> You are the Editor, the entry point of the Revision Loop. You may run multiple times within a single article — once on the original draft, then once after each Revision Writer pass.
>
> Steps every iteration:
>
> 1. **Accuracy check.** Verify every factual claim against the research dossiers. Flag unverifiable claims and weaken or remove.
>
> 2. **Copyright check.** No quoted spans ≥ 15 words. No source quoted twice. Rewrite violations as paraphrase.
>
> 3. **Prose polish.** Tighten weak sentences. Cut filler. Hook in first 50 words.
>
> 4. **Weave in image assets.** For each entry in `state["image_assets"]`, replace the matching `<!-- IMAGE: <position> -->` marker with `![alt_text](url)`. Cover image after title/subtitle, before opening paragraph.
>
> 5. **Weave in video.** If `state["video_asset"]` is not None, replace `<!-- VIDEO: hero -->` with `![Tutorial preview](gif_url)` followed by `Watch the full tutorial: [download MP4](mp4_url)`. If video_asset is None, replace marker with empty line.
>
> 6. **Repo link integration.** If `state["repo_url"]` is set, weave naturally into setup section and "Next steps."
>
> 7. **Format and post.** Call `medium_format` on the polished markdown. Then call `telegram_post_for_approval` with the formatted article, `repo_url`, and an `asset_summary` like "1 cover + 2 inline images, 8s tutorial GIF, GitHub repo ✓." Wait for response.
>
> 8. **Branch on verdict:**
>    - **`approve`**: Write `state["final_article"]` (the polished markdown), `state["editor_verdict"] = "approve"`, `state["medium_draft_url"]`. Call `memory_bank_add_fact` with `fact = "Covered <release> on <today>"`, metadata including release_url, article URL, repo_url, asset bundle URLs. Set `tool_context.actions.escalate = True` to break the loop.
>    - **`reject`**: Write `state["editor_verdict"] = "reject"` and `state["final_article"]` (whatever the latest version is, for archival). Do NOT add to Memory Bank — a rejected article shouldn't block re-attempting the same release later. Set `tool_context.actions.escalate = True` to break the loop.
>    - **`revise`**: Write `state["editor_verdict"] = "revise"` and `state["human_feedback"]` = the feedback string returned by the tool. Do NOT escalate. The Revision Writer will pick up next.
>    - **timeout (no response in 24h)**: Write `state["editor_verdict"] = "pending_human"`. Set `tool_context.actions.escalate = True` and exit cleanly. The article does not ship; a future manual trigger can resume.
>
> Constraint: never re-add to Memory Bank if you've already added in a prior iteration of this loop. If `state["memory_bank_recorded"]` is True, skip step 8's Memory Bank call.

### 10. Revision Writer (in revision loop)

**Role:** Incorporate human feedback and rewrite the draft. Only runs when the Editor's verdict is `revise`; otherwise exits immediately.

**Model:** Gemini 3.1 Pro.

**Tools:** None — pure rewriting over state.

**Instruction prompt:**

> You are the Revision Writer. You only run when the Editor has captured human feedback for revision.
>
> First line: if `state["editor_verdict"] != "revise"` or `state["human_feedback"]` is missing or empty, end your turn immediately without using tools.
>
> Otherwise:
> 1. Read `state["draft"]` (the current draft) and `state["human_feedback"]` (the human's revision request).
> 2. Read `state["outline"]` and the research dossiers as needed for context.
> 3. Rewrite the draft to incorporate the feedback faithfully. Preserve all `<!-- IMAGE: ... -->` and `<!-- VIDEO: hero -->` markers — the Editor needs them for re-weaving assets. Preserve the overall structure unless the feedback explicitly asks for restructuring.
> 4. Write the revised markdown back to `state["draft"]`.
> 5. Clear `state["editor_verdict"]` (set to None) so the next Editor pass treats it as a fresh review. Leave `state["human_feedback"]` in place for traceability — the next Editor iteration knows what feedback was applied.
>
> Constraints: do NOT change the title or subtitle unless the feedback specifically asks for it. Do NOT remove asset markers. Do NOT add new factual claims that aren't supported by the research dossiers.

**Loop termination:** `LoopAgent(max_iterations=3, sub_agents=[editor, revision_writer])`. The loop exits early when Editor escalates (approve, reject, or timeout). At max iterations, the latest draft is whatever Revision Writer last produced — if Editor never approves within 3 rounds, the article does not ship and `editor_verdict` will be `revise` (treat as not-shipped on the orchestrator side).

## Top-level orchestration

```python
# main.py — the wiring
from google.adk.agents import SequentialAgent, ParallelAgent, LoopAgent, LlmAgent

from agents.scout import scout
from agents.triage import triage
from agents.topic_gate import topic_gate
from agents.researchers import docs_researcher, github_researcher, context_researcher
from agents.architect import architect
from agents.writer import drafter, critic
from agents.asset import image_asset_agent, video_asset_agent
from agents.repo_builder import repo_builder
from agents.editor import editor
from agents.revision_writer import revision_writer

# Researcher pool — three Gemini Flash agents in parallel
researcher_pool = ParallelAgent(
    name="researcher_pool",
    sub_agents=[docs_researcher, github_researcher, context_researcher],
)

# Writer loop — drafter ↔ critic, max 3 iterations (LLM-driven)
writer_loop = LoopAgent(
    name="writer_loop",
    max_iterations=3,
    sub_agents=[drafter, critic],
)

# Asset Agent — image + video sub-agents in parallel
asset_agent = ParallelAgent(
    name="asset_agent",
    sub_agents=[image_asset_agent, video_asset_agent],
)

# Conditional repo router
repo_router = LlmAgent(
    name="repo_router",
    model="gemini-3.1-flash",
    instruction=(
        "Look at state['needs_repo']. If True, transfer to the repo_builder "
        "sub-agent. If False or missing, do nothing and end your turn."
    ),
    sub_agents=[repo_builder],
)

# Post-writer parallel — assets and repo run concurrently
post_writer_parallel = ParallelAgent(
    name="post_writer_parallel",
    sub_agents=[asset_agent, repo_router],
)

# Revision loop — editor + revision writer, max 3 iterations (human-driven)
revision_loop = LoopAgent(
    name="revision_loop",
    max_iterations=3,
    sub_agents=[editor, revision_writer],
)

# Top-level pipeline
root_agent = SequentialAgent(
    name="ai_release_to_article_pipeline",
    sub_agents=[
        scout,
        triage,
        topic_gate,            # human gate #1
        researcher_pool,
        architect,
        writer_loop,
        post_writer_parallel,
        revision_loop,         # human gate #2 (looped)
    ],
)
```

**Early-exit pattern.** When Triage or the Topic Gate sets `chosen_release = None`, every downstream agent needs to bail. Prepend to every agent from Researcher onward (including those inside ParallelAgent and LoopAgent containers): *"If `state['chosen_release']` is None, end your turn immediately without using tools."* This is more reliable than mutating the orchestrator in code.

**Concurrency note.** Sessions are isolated. If a Topic Gate or Revision Loop is waiting on a human response when the next Cloud Scheduler tick fires, a fresh session starts in parallel. Multiple in-flight pipelines are fine — they don't share state. Worst case you have 3-4 pending Telegram approvals queued up; respond to them in any order.

## Tools to implement

| Tool | Used by | Implementation |
|------|---------|----------------|
| `poll_arxiv` | Scout | `arxiv` PyPI package |
| `poll_github_trending` | Scout | scrape `github.com/trending` |
| `poll_rss` | Scout | `feedparser` |
| `poll_hf_models` | Scout | `huggingface_hub` library |
| `memory_bank_search` | Triage | ADK Memory Bank client |
| `memory_bank_add_fact` | Topic Gate, Editor | ADK Memory Bank client |
| `telegram_post_topic_for_approval` | Topic Gate | `python-telegram-bot` with 2-button inline keyboard, 24h timeout |
| `web_fetch`, `google_search` | Researchers | ADK built-in |
| `github_get_*` (read), `github_create_repo`, `github_commit_files`, `github_set_topics` | GitHub researcher, Repo Builder | `PyGithub` |
| `run_python_snippet` | Critic | ADK Code Execution tool |
| `generate_image` | Image Asset Agent | Vertex AI → Nano Banana 2 |
| `generate_video` | Video Asset Agent | Vertex AI → Veo 3.1 Fast |
| `convert_to_gif`, `extract_first_frame` | Video Asset Agent | local `ffmpeg-python` |
| `upload_to_gcs` | Image + Video Asset Agents | `google-cloud-storage` |
| `medium_format` | Editor | local function |
| `telegram_post_for_approval` | Editor | `python-telegram-bot` with 3-button inline keyboard + ForceReply for feedback, 24h timeout per round |

The two Telegram tools are similar but distinct: `topic_for_approval` has 2 buttons, `for_approval` (Editor) has 3 buttons plus a feedback-capture flow. Implement them as two separate functions in `tools/telegram_approval.py` to keep the per-button logic clean.

Secrets in **Google Secret Manager**: GitHub PAT, Telegram bot token, Vertex service account.

## Memory Bank schema

Two fact types now:

**Successful coverage** (written by Editor on Approve):
```json
{
  "scope": "ai_release_pipeline",
  "fact": "Covered Anthropic Skills release on 2026-04-22",
  "metadata": {
    "release_url": "...", "release_source": "anthropic",
    "release_published_at": "...", "article_url": "...",
    "repo_url": "...", "asset_bundle": {"cover_url": "...", "video_url": "..."},
    "covered_at": "2026-04-22T18:30:00Z",
    "type": "covered"
  }
}
```

**Human-rejected topic** (written by Topic Gate on Skip):
```json
{
  "scope": "ai_release_pipeline",
  "fact": "Human rejected topic: <release title>",
  "metadata": {
    "release_url": "...", "release_source": "...",
    "rejected_at": "2026-04-22T18:30:00Z",
    "type": "human-rejected"
  }
}
```

Triage's `memory_bank_search` query at runtime: `"Have we encountered <release_title>?"` with similarity threshold 0.85. Both `covered` and `human-rejected` types are hard filters — the same release won't re-surface after either outcome.

## Repository layout

```
ai-release-pipeline/
├── README.md
├── DESIGN.md
├── pyproject.toml
├── .env.example
├── Makefile
├── agents/
│   ├── __init__.py
│   ├── scout/
│   ├── triage/
│   ├── topic_gate/                  # NEW v1.2
│   │   ├── __init__.py
│   │   └── agent.py
│   ├── researchers/
│   │   ├── docs.py
│   │   ├── github.py
│   │   └── context.py
│   ├── architect/
│   ├── writer/
│   │   ├── drafter.py
│   │   └── critic.py
│   ├── asset/
│   │   ├── image.py
│   │   └── video.py
│   ├── repo_builder/
│   ├── editor/
│   └── revision_writer/             # NEW v1.2
│       ├── __init__.py
│       └── agent.py
├── tools/
│   ├── pollers.py
│   ├── github_ops.py
│   ├── imagen.py
│   ├── veo.py
│   ├── video_processing.py
│   ├── gcs.py
│   ├── medium.py
│   └── telegram_approval.py         # MODIFIED v1.2: now exports two functions
├── shared/
│   ├── models.py                    # MODIFIED v1.2: TopicVerdict, RevisionFeedback added
│   ├── prompts.py
│   └── memory.py
├── eval/
│   ├── eval_set.evalset.json
│   └── synthetic_releases.json
├── deploy/
│   ├── deploy.sh
│   ├── scheduler.tf
│   ├── gcs_bucket.tf
│   └── secrets.tf
└── main.py
```

## Claude Code prompt library — build sequence

13 steps now. Build in order; each assumes the previous has shipped. Claude Code reads `DESIGN.md` for context.

### Step 0 — scaffold the repo

```
You are setting up a Python ADK project for the multi-agent system described in DESIGN.md. Read DESIGN.md fully before doing anything.

Tasks:
1. Create the directory tree exactly as shown in the "Repository layout" section.
2. Initialize a pyproject.toml targeting Python 3.12 with dependencies: google-adk>=1.31, google-cloud-aiplatform, google-cloud-storage, PyGithub, feedparser, arxiv, huggingface_hub, python-telegram-bot, pydantic, ffmpeg-python, Pillow.
3. Create a Makefile with these targets: setup, run-local, run-web, eval, deploy, trigger, logs, clean.
4. Create .env.example with placeholders for: GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION, GOOGLE_GENAI_USE_VERTEXAI, GITHUB_TOKEN, GITHUB_ORG, TELEGRAM_BOT_TOKEN, TELEGRAM_APPROVAL_CHAT_ID, GCS_ASSETS_BUCKET.
5. Create shared/models.py with Pydantic models for: Candidate, ChosenRelease, TopicVerdict, ResearchDossier, Outline, ImageBrief, VideoBrief, ImageAsset, VideoAsset, Draft, RevisionFeedback, EditorVerdict — match field names used in DESIGN.md state keys.
6. Stop. Do not implement any agents yet. Show me the file tree.
```

### Step 1 — Scout

```
Read DESIGN.md section "1. Scout".

Implement tools/pollers.py (poll_arxiv, poll_github_trending, poll_rss, poll_hf_models — each takes since: datetime, returns list[Candidate], graceful network failure handling, comprehensive docstrings) and agents/scout/agent.py (LlmAgent on gemini-3.1-flash, all four polling tools wired, instruction from DESIGN.md verbatim — store in shared/prompts.py first).

Add tests/test_scout.py with mocked pollers verifying state["candidates"] is populated.

Confirm pytest is green.
```

### Step 2 — Triage + Memory Bank

```
Read DESIGN.md sections "2. Triage" and "Memory Bank schema".

Implement shared/memory.py (MemoryBankClient wrapper with search(query, threshold=0.85) and add_fact(scope, fact, metadata) methods) and agents/triage/agent.py (LlmAgent on gemini-3.1-flash, memory_bank_search wired, instruction from DESIGN.md).

Note: Triage's output now includes top_alternatives — include this in the ChosenRelease Pydantic model.

Add tests/test_triage.py covering: high-score pass-through, dedupe via Memory Bank (both 'covered' and 'human-rejected' fact types), no-candidates → chosen_release=None.
```

### Step 3 — Topic Gate (NEW)

```
Read DESIGN.md section "3. Topic Gate".

Implement:
- tools/telegram_approval.py — start with telegram_post_topic_for_approval(chosen_release, rationale, top_alternatives) -> TopicVerdict. Use python-telegram-bot. Post a markdown-formatted message with the topic title, source, score, rationale, URL, and (collapsed) up to 2 alternatives. Two inline buttons: Approve, Skip. Block until callback received OR 24h timeout. Return TopicVerdict.
- agents/topic_gate/agent.py — LlmAgent on gemini-3.1-flash. Tools: telegram_post_topic_for_approval, memory_bank_add_fact. Instruction from DESIGN.md verbatim.

Test: fixture chosen_release + mocked Telegram approve → state unchanged, topic_verdict="approve". Fixture + mocked skip → chosen_release=None, memory_bank_add_fact called with type="human-rejected". Fixture + mocked timeout → chosen_release=None, NO Memory Bank call.
```

### Step 4 — Researcher pool

```
Read DESIGN.md section "4. Researcher (Parallel)".

Implement three LlmAgents under agents/researchers/. All use gemini-3.1-flash. Each agent's first instruction line: "If state['chosen_release'] is None, end your turn immediately."

- docs_researcher: tools = [web_fetch, google_search]
- github_researcher: extend tools/github_ops.py with PyGithub read wrappers (github_get_repo, github_get_readme, github_list_files)
- context_researcher: tool = google_search

Wrap them in ParallelAgent("researcher_pool", ...) in main.py.

Test: mock chosen_release fixture, all three state keys populate. Then mock chosen_release=None, all three exit immediately.
```

### Step 5 — Architect

```
Read DESIGN.md section "5. Architect".

Implement agents/architect/agent.py — LlmAgent on gemini-3.1-pro, no tools. First instruction line: chosen_release=None early exit. Instruction body from DESIGN.md.

Tests/test_architect.py with three fixtures: quickstart with code (expect needs_repo=True, image_brief 3-4 specs, possibly needs_video=True), explainer no code (needs_repo=False, image_brief still populated, needs_video=False), release_recap (minimal everything).
```

### Step 6 — Writer loop

```
Read DESIGN.md section "6. Writer (Loop)".

Implement agents/writer/drafter.py and agents/writer/critic.py both on gemini-3.1-pro. Drafter inserts <!-- IMAGE: <position> --> and <!-- VIDEO: hero --> placeholders matching briefs. Critic wires ADK Code Execution, verifies markers present before accepting, calls tool_context.actions.escalate = True on accept.

Define writer_loop = LoopAgent(name="writer_loop", max_iterations=3, sub_agents=[drafter, critic]) in main.py.

Test: simple outline + briefs → draft produced with markers, loop terminates on accept, stops at iter 3 without accept.
```

### Step 7 — Asset Agent (Image + Video)

```
Read DESIGN.md section "7. Asset Agent".

Implement:
- tools/gcs.py — upload_to_gcs(bytes_data, content_type, slug) -> public_url. Bucket from GCS_ASSETS_BUCKET env var. Configure via deploy/gcs_bucket.tf with public-read and 90-day lifecycle.
- tools/imagen.py — generate_image(prompt, aspect_ratio, style) -> bytes. Calls Nano Banana 2 via Vertex.
- tools/veo.py — generate_video(prompt, duration_seconds, aspect_ratio) -> bytes. Calls Veo 3.1 Fast. Cap at 8s.
- tools/video_processing.py — convert_to_gif and extract_first_frame using ffmpeg-python.
- agents/asset/image.py and agents/asset/video.py per DESIGN.md. Video agent's first instruction line is the needs_video early exit.

Wrap in ParallelAgent("asset_agent", ...) in main.py.

Test: fixture brief + real GCS bucket, generate cover image, verify URL reachable. Test video with needs_video True (one short test video) and False (verify no Veo call).
```

### Step 8 — Repo Builder + router

```
Read DESIGN.md section "8. Repo Builder (conditional)".

Extend tools/github_ops.py with write ops: github_create_repo, github_commit_files (binary blob support for assets), github_set_topics. Use PyGithub.

Implement agents/repo_builder/agent.py on gemini-3.1-pro. Instruction includes the asset-bundle commit responsibility.

In main.py: repo_router = LlmAgent(name="repo_router", model="gemini-3.1-flash", instruction="...", sub_agents=[repo_builder]). Then post_writer_parallel = ParallelAgent(name="post_writer_parallel", sub_agents=[asset_agent, repo_router]).

Test with two fixtures: needs_repo=True (verify repo created, assets committed in /assets) and False (nothing happens). Use a test-only org and clean up.
```

### Step 9 — Editor (in revision loop, MODIFIED)

```
Read DESIGN.md section "9. Editor".

Extend tools/telegram_approval.py with telegram_post_for_approval(article, repo_url, asset_summary) -> EditorVerdict. THREE inline buttons (Approve/Reject/Revise). On Revise, send ForceReply prompt and capture next message in chat as feedback. Return EditorVerdict {verdict, feedback, at}. 24h timeout per round.

Implement agents/editor/agent.py — LlmAgent on gemini-3.1-pro. Tools: medium_format, telegram_post_for_approval, memory_bank_add_fact. Instruction from DESIGN.md — note the 3-way verdict branching, the Memory Bank call only on Approve and only once per loop, and the asset-marker re-weaving.

Implement tools/medium.py — medium_format(markdown: str) -> str. Handle Medium quirks (code fences, header levels, GIF embeds, MP4 links).

Test fixtures: draft with all markers + image_assets + video_asset + repo_url → mocked Approve verdict → final_article populated, memory_bank_add_fact called once. Mocked Revise verdict → editor_verdict="revise", human_feedback set, memory_bank_add_fact NOT called. Mocked Reject → editor_verdict="reject", no memory bank call.
```

### Step 10 — Revision Writer (NEW)

```
Read DESIGN.md section "10. Revision Writer".

Implement agents/revision_writer/agent.py — LlmAgent on gemini-3.1-pro, no tools. Instruction from DESIGN.md verbatim. First line: "If state['editor_verdict'] != 'revise' or state['human_feedback'] is missing, end your turn immediately."

In main.py: revision_loop = LoopAgent(name="revision_loop", max_iterations=3, sub_agents=[editor, revision_writer]).

Test fixtures: editor_verdict='revise' + feedback "make it shorter" + draft → revised draft is shorter, markers preserved, editor_verdict cleared. editor_verdict='approve' → exits immediately, draft unchanged.
```

### Step 11 — Wire the full pipeline

```
Update main.py to compose root_agent as shown in DESIGN.md "Top-level orchestration":
scout → triage → topic_gate → researcher_pool → architect → writer_loop → post_writer_parallel → revision_loop.

For every agent from researcher_pool onward (including those inside containers), prepend: "If state['chosen_release'] is None, end your turn immediately without using tools."

Run `adk web` and walk through three end-to-end executions:
1. A real release approved at Topic Gate, approved at Editor on first pass.
2. A real release skipped at Topic Gate (verify Memory Bank fact written, run ends cleanly).
3. A real release approved at Topic Gate, then revised once at Editor (verify Revision Writer rewrites, Editor re-presents, second pass approves).

Capture the trace screenshots for the README. Pay attention to the parallel block timing (asset gen vs repo gen) and the revision loop iteration timing.
```

### Step 12 — Deploy and schedule

```
Read DESIGN.md "Deployment & triggering".

Implement:
- deploy/gcs_bucket.tf — assets bucket, uniform-bucket-level-access, public-read at object level, 90-day lifecycle, US multi-region.
- deploy/deploy.sh — `adk deploy agent_engine` with project, region, service account. Output reasoningEngines/... resource ID.
- deploy/scheduler.tf — Cloud Scheduler hourly cron + Pub/Sub + Cloud Function POSTing to Agent Runtime.
- deploy/secrets.tf — Secret Manager: GITHUB_TOKEN, TELEGRAM_BOT_TOKEN.

Test: `make deploy`, then `gcloud scheduler jobs run ai-release-pipeline-hourly`. Watch logs. Confirm a full run completes with both human gates working in production.
```

## Deployment & triggering

(Same as v1.1 — Cloud Scheduler hourly → Pub/Sub → Cloud Function → Agent Runtime endpoint. Agent Runtime over Cloud Run for sub-second cold starts, integrated Memory Bank, OTel observability. IAM and quota notes unchanged.)

**One operational note for v1.2:** with two human gates, you'll want a Cloud Monitoring alert on the metric "average Topic Gate response time" and "average Revision Loop completion time." If either grows past 6-12h sustained, the pipeline is queueing up faster than you can respond — tighten the polling cadence or the Triage threshold.

## Cost back-of-envelope

Largely unchanged from v1.1 — the human gates are essentially free (Telegram API + a few Flash tokens for orchestration). The bigger cost shift is downward: Topic Gate skips kill ~30-40% of pipelines before research starts, eliminating the most expensive stage on the topics you wouldn't have published anyway.

| Item | Monthly |
|------|---------|
| Scout + Triage + Topic Gate on Flash (720 runs at $0.001) | $0.70 |
| Research → Editor (Pro, ~10 articles after topic-gate skips, 1 revision avg) | $4.50 |
| Image generation (~4 × 10 × $0.04) | $1.60 |
| Video generation (Veo 3.1 Fast, 8s × ~7 × $0.30) | $16.80 |
| Agent Runtime baseline | $5.00 |
| Memory Bank | $0.50 |
| GCS storage | $0.10 |
| Cloud Scheduler + Pub/Sub + Function | $0.10 |
| **Total** | **~$29/month** |

Slightly cheaper than v1.1 net of more skips at the Topic Gate. Same dial-down levers apply: shorter videos, tighter video gating, or replace Veo with Nano Banana 2 storyboard-GIFs for ~$10/month total.

## Open assumptions and questions

- **Topic Gate alternatives surfacing.** Currently the gate posts the chosen release with `top_alternatives` in the message body for context, but only Approve/Skip buttons. If you want one-tap "actually pick #2 instead," the tool can grow more buttons — but each alternative needs its own button, which gets unwieldy. The cleaner UX is to add a "/show_alternatives" command that the bot responds to with a follow-up message containing per-alternative buttons. Worth it?
- **Revision feedback format.** Currently free-text Telegram reply. Could template into a 3-question form ("What's the main issue? What should change? Any specific section?") for more actionable feedback. Free-text is more flexible; templates are more reliable. Lean which way?
- **Max revision iterations: 3.** If the article isn't good after 3 human revision passes, the system gives up. Lift to 5 if you'd rather grind it out, or drop to 2 if you'd rather kill articles that aren't working.
- **24-hour timeout per gate.** A single article can stall up to 24h at Topic Gate plus 24h × 3 at Revision Loop = ~96h worst case. If that's too long, tighten timeouts — but understand that shorter timeouts mean more articles end as `pending_human` and need manual re-trigger.
- **Concurrency: unbounded sessions.** Multiple in-flight runs queue up if you don't respond promptly. No rate limiting on the polling side. If this becomes overwhelming, add a guard: skip the hourly trigger if there are already N pipelines pending at Topic Gate.
- **Image style decisions in Architect.** Same as v1.1 — Architect picks per-image style. You may want a pinned house style.
- **Approval channel: Telegram.** Slack is a one-tool swap if EY teammate visibility matters in v2.
- **Asset hosting: public GCS bucket.** Same as v1.1.
- **Auto-publishing to Medium.** Still not implemented. Editor produces Medium-formatted markdown, posts for approval, on Approve you copy-paste into Medium's editor. Medium API is read-only for non-partners.

If those land roughly right, the path forward is: Step 0 of the prompt library, then iterate one agent at a time. Build Scout → Triage → Topic Gate first to validate the human-gate pattern end-to-end (you'll learn the most about the Telegram tool here). Then Researcher through Editor for the article path. Then Revision Writer + the loop wiring. Don't over-engineer the first version — the design's whole reason for breaking into ten small agents is that each one is editable in isolation when something misfires.
