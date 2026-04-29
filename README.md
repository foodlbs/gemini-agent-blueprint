# ai-release-pipeline

Polling multi-agent content pipeline for AI releases on Gemini ADK. See
[DESIGN.md](DESIGN.md) for full architecture and rationale.

## What it does

Polls major AI release sources (arXiv, GitHub trending, Anthropic/OpenAI/Google
blogs, Hugging Face) on an hourly schedule. When a release is significant
enough to write about, it asks a human (via Telegram) for approval, then
researches → outlines → drafts → critiques → generates assets (images +
optional video) → optionally builds a starter repo → has a human approve the
final article (with revise loop). Memory Bank dedupes against past coverage
and human-rejected topics so the same release doesn't re-surface.

## Pipeline shape

Ten agents composed via ADK orchestration primitives:

```
SequentialAgent: ai_release_to_article_pipeline
├── scout                    LlmAgent (Flash)         → state["candidates"]
├── triage                   LlmAgent (Flash)         → state["chosen_release"]
├── topic_gate               LlmAgent (Flash)         human gate #1, Telegram
├── ParallelAgent: researcher_pool
│   ├── docs_researcher      LlmAgent (Flash)         → state["docs_research"]
│   ├── github_researcher    LlmAgent (Flash)         → state["github_research"]
│   └── context_researcher   LlmAgent (Flash)         → state["context_research"]
├── architect                LlmAgent (Pro)           → outline + briefs
├── LoopAgent: writer_loop (max_iterations=3)
│   ├── drafter              LlmAgent (Pro)           → state["draft"]
│   └── critic               LlmAgent (Pro, code exec) accept → escalate
├── ParallelAgent: post_writer_parallel
│   ├── ParallelAgent: asset_agent
│   │   ├── image_asset_agent  LlmAgent (Flash)       → state["image_assets"]
│   │   └── video_asset_agent  LlmAgent (Flash)       → state["video_asset"]
│   └── repo_router          LlmAgent (Flash, conditional)
│       └── repo_builder     LlmAgent (Pro)           → state["repo_url"]
└── LoopAgent: revision_loop (max_iterations=3)
    ├── editor               LlmAgent (Pro)           human gate #2, Telegram
    └── revision_writer      LlmAgent (Pro)           → state["draft"] (rewritten)
```

## Setup

```bash
# 1. Install deps
make setup        # uv sync

# 2. Configure environment
cp .env.example .env
# Fill in: GOOGLE_CLOUD_PROJECT, TELEGRAM_BOT_TOKEN, TELEGRAM_APPROVAL_CHAT_ID,
# GITHUB_TOKEN, GITHUB_ORG, GCS_ASSETS_BUCKET

# 3. Provision the assets bucket (one-time)
cd deploy && terraform init && terraform apply
# This creates the public-read GCS bucket with a 90-day lifecycle.

# 4. Run tests
uv run pytest -q
```

## Local development with `adk web`

```bash
make run-web      # uv run adk web .
# Opens at http://127.0.0.1:8000 by default.
```

The pipeline is exposed under the `pipeline` agent name. Open the web UI,
select `pipeline`, and send any message — the Scout will start polling
automatically (the message is just a kick).

`adk web` discovers agents by looking for subdirectories with `__init__.py`
and `agent.py` exposing `root_agent`. The `pipeline/` directory at the
project root is a thin wrapper that re-exports `root_agent` from `main.py`.

## End-to-end walkthroughs

The full pipeline requires GCP credentials (Vertex AI for Gemini/Imagen/Veo +
GCS), a Telegram bot, and a GitHub PAT. Three runs exercise the verdict
matrix per DESIGN.md "Top-level orchestration":

### Run 1 — happy path

1. Trigger a polling cycle (manual: open `adk web`, select `pipeline`,
   send any message; or scheduled: `make trigger`).
2. Topic Gate posts the chosen release to Telegram. Tap **Approve**.
3. Researcher pool runs (3 sub-agents in parallel, ~10–30s each).
4. Architect produces the outline + image_brief + video_brief.
5. Writer loop iterates drafter ↔ critic until the critic accepts
   (typically 1–2 iterations).
6. `post_writer_parallel` runs the asset_agent and repo_router
   concurrently — note the timing in the trace: image generation
   (~30s × 3) and video generation (~60s) overlap with repo creation
   and commit (~5s).
7. Editor weaves assets, posts the final article to Telegram. Tap **Approve**.
8. Memory Bank records the `covered` fact. Pipeline exits.

### Run 2 — Topic Gate skip

1. Trigger a polling cycle.
2. Topic Gate posts the chosen release. Tap **Skip**.
3. Topic Gate calls `memory_bank_add_fact` with `type="human-rejected"`.
4. `chosen_release` is cleared to None; every downstream agent's
   first-line early-exit short-circuits.
5. Pipeline exits cleanly. The next polling cycle won't re-surface the
   skipped release (Triage's Memory Bank dedupe filters it).

### Run 3 — Editor revision

1. Trigger a polling cycle. Approve at Topic Gate.
2. Pipeline runs through to Editor.
3. Editor posts the draft. Tap **Revise**, then reply to the bot's
   ForceReply prompt with concrete feedback (e.g., "tighten section 2").
4. Editor records `editor_verdict="revise"` and `human_feedback`.
5. Revision Writer rewrites the draft, preserving asset markers; clears
   `editor_verdict` to None.
6. Editor re-presents the rewritten draft. Tap **Approve**.
7. Memory Bank records the `covered` fact (only once — the
   `memory_bank_recorded` flag set by the after-tool callback prevents
   double-recording across iterations).

Trace screenshots for all three runs go in `docs/traces/` (manual capture
from the `adk web` event panel — the timing of the parallel block in Run 1
and the loop iteration timing in Run 3 are the most informative).

## Project layout

```
.
├── main.py                          root_agent + container wiring
├── pipeline/                        adk web discovery wrapper
├── agents/<name>/agent.py           one LlmAgent per sub-agent
├── tools/                           polling, GCS, Imagen, Veo, ffmpeg, GitHub, Telegram, Medium
├── shared/
│   ├── models.py                    Pydantic state-key contracts
│   ├── prompts.py                   instruction strings (DESIGN.md verbatim)
│   └── memory.py                    Memory Bank wrapper (local + Vertex)
├── tests/                           173 unit/integration tests
├── eval/                            ADK eval set (synthetic releases)
└── deploy/                          Terraform + deploy.sh
```

## Tests

```bash
uv run pytest -q                     # all 173 tests, ~1.5s
```

Two integration tests are skipped by default (they need real credentials):

- `tests/test_assets.py::test_upload_to_gcs_real_bucket_returns_reachable_url`
  — opt in by setting `GCS_ASSETS_BUCKET` to a provisioned bucket name.
- `tests/test_repo_builder.py::test_repo_builder_real_integration_creates_and_commits_then_cleans_up`
  — opt in by setting `GITHUB_TOKEN` and `GITHUB_TEST_ORG`. The test creates
  a repo and deletes it on teardown.

## Deployment

See [DESIGN.md "Deployment & triggering"](DESIGN.md) for the high-level
architecture: Cloud Scheduler (hourly cron) → Pub/Sub → Cloud Function →
Agent Engine. Three Terraform files plus one shell script in `deploy/`
provision and ship the pipeline.

### Files

- [deploy/gcs_bucket.tf](deploy/gcs_bucket.tf) — public-read assets bucket
  with uniform IAM and 90-day lifecycle.
- [deploy/secrets.tf](deploy/secrets.tf) — Secret Manager secrets for
  `GITHUB_TOKEN` and `TELEGRAM_BOT_TOKEN`, plus per-secret IAM grants to
  the Agent Engine service account.
- [deploy/scheduler.tf](deploy/scheduler.tf) — Cloud Scheduler hourly job,
  Pub/Sub trigger topic, Cloud Function (Gen2) that POSTs to Agent
  Engine; two least-privilege service accounts (function vs scheduler).
- [deploy/deploy.sh](deploy/deploy.sh) — `adk deploy agent_engine`
  wrapper; extracts the `reasoningEngines/NNNNN` resource ID and prints
  the next-step terraform invocation.

### One-time setup

```bash
# 1. Provision the assets bucket (no agent yet — needed for the runtime env)
cd deploy
terraform init
terraform apply -target=google_storage_bucket.assets \
                -var=gcs_assets_bucket=my-prod-bucket

# 2. Create the Agent Engine service account that secrets.tf will grant
#    secretAccessor to (and that Agent Engine itself runs as):
gcloud iam service-accounts create ai-release-pipeline \
    --display-name="AI release pipeline runtime" \
    --project="$GOOGLE_CLOUD_PROJECT"
```

### Deploy the pipeline

```bash
# 3. Build + deploy to Agent Engine. Outputs reasoningEngines/NNNNN.
make deploy
# (equivalent to: bash deploy/deploy.sh)

# 4. (one-time) attach the service account to the deployed Agent Engine.
#    deploy.sh prints this exact command with the right resource name.

# 5. Apply the rest of the terraform (scheduler + secrets):
cd deploy
TF_VAR_github_token="$GITHUB_TOKEN" \
TF_VAR_telegram_bot_token="$TELEGRAM_BOT_TOKEN" \
terraform apply \
    -var=google_cloud_project="$GOOGLE_CLOUD_PROJECT" \
    -var=google_cloud_location="$GOOGLE_CLOUD_LOCATION" \
    -var=gcs_assets_bucket="$GCS_ASSETS_BUCKET" \
    -var=agent_engine_resource_id="$(cat .last_resource_id)" \
    -var=agent_engine_sa_email="ai-release-pipeline@${GOOGLE_CLOUD_PROJECT}.iam.gserviceaccount.com"
```

### Verify

```bash
# 6. Trigger one run on demand
gcloud scheduler jobs run ai-release-pipeline-hourly \
    --location="$GOOGLE_CLOUD_LOCATION"

# 7. Watch the function and Agent Engine logs
make logs
# or:
gcloud functions logs read ai-release-pipeline-trigger \
    --region="$GOOGLE_CLOUD_LOCATION" --limit=50
```

A full first run — through both human gates, Editor approval, asset
generation, optional repo creation — takes anywhere from 5 minutes (no
revise + no video) to several hours (24h max wait per Telegram gate).
The pipeline runs detached in Agent Engine; the Cloud Function only
kicks off the run and exits.

### Operational alerting (DESIGN.md v1.2 note)

Once running, set up Cloud Monitoring alerts for:
- Average **Topic Gate response time** (24h timeout per round; sustained
  >6–12h means the queue is backing up).
- Average **Revision Loop completion time** (worst case 24h × 3 = 72h;
  same threshold).

If either alert fires consistently, tighten the polling cadence (cron in
`scheduler.tf`) or the Triage threshold (`shared/prompts.py`).
