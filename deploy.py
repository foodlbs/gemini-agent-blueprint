"""One-shot deployer for the gemini-agent-blueprint — DESIGN.v2.md §10.1.

Run from the repo root:

    uv run python deploy.py

REQUIRED ENV (from .env or shell):
  GOOGLE_CLOUD_PROJECT        GCP project ID (e.g. gen-lang-client-0366435980)
  GITHUB_ORG                  GitHub org/user that owns release-tracked repos
  TELEGRAM_APPROVAL_CHAT_ID   Telegram chat ID for HITL approval messages

OPTIONAL ENV (with defaults):
  REGION                      default "us-west1"
  PROJECT_DISPLAY_NAME        default "gemini-agent-blueprint"
  PROJECT_APP_NAME            default "gemini_agent_blueprint" (Python ident)
  TF_VAR_project_name         default "gab" — drives SA / secret / bucket names

INVARIANTS:
  - Region must be a regional endpoint (default us-west1). Do NOT read from
    GOOGLE_CLOUD_LOCATION — that is "global" locally for Gemini calls
    and would fail agent_engines.create which requires a regional
    endpoint.
  - The engine's runtime SA is `{PROJECT_PREFIX}-app@PROJECT.iam` (§10.3) —
    must exist before this script runs (provisioned via terraform).
  - Two Secret Manager secrets must exist: {PROJECT_PREFIX}-github-token,
    {PROJECT_PREFIX}-telegram-bot-token (§10.4).
  - Staging GCS bucket gs://PROJECT-{PROJECT_PREFIX}-staging must exist —
    Vertex SDK uploads the source tarball there but does NOT create it.

API NOTE (deviation from DESIGN.v2.md §10.1):
  The design's example used `vertexai.preview.reasoning_engines.
  ReasoningEngine.create()` — that signature does not accept env_vars
  or service_account. The supported public API is `vertexai.agent_engines
  .create()` (added in google-cloud-aiplatform 1.105+). Secrets are
  passed inline within env_vars using `aip_types.SecretRef` instead of
  a separate `secret_environment_variables` kwarg.

MEMORY BANK NOTE:
  Memory Bank is attached to the ReasoningEngine itself — there is no
  separate "memory bank" resource to provision. Inside the deployed
  runtime, GOOGLE_CLOUD_AGENT_ENGINE_ID is auto-set; tools/memory.py
  reads it to construct VertexAiMemoryBankService.

OUTPUT:
  Writes the engine resource ID to deploy/.deployed_resource_id
  (gitignored). On re-runs, the file's presence triggers .update()
  instead of .create().
"""

from __future__ import annotations

import os
import pathlib
import sys


# Region pin — independent of GOOGLE_CLOUD_LOCATION. Default us-west1 because
# Vertex AI Agent Runtime requires a regional endpoint and that's where
# the reference deployment lives. Override with REGION env var if needed.
REGION         = os.environ.get("REGION", "us-west1")

# Display name shown in the Vertex AI Agent Runtime console.
DISPLAY        = os.environ.get("PROJECT_DISPLAY_NAME", "gemini-agent-blueprint")

# Internal app_name passed to AdkApp — must be a valid Python identifier
# (no hyphens). Used by the ADK runtime to resolve the agent module.
APP_NAME       = os.environ.get("PROJECT_APP_NAME", "gemini_agent_blueprint")

# Resource-name prefix shared with terraform. Drives SA names, secret
# names, bucket names. Default "gab" matches terraform's var.project_name
# default. If you set TF_VAR_project_name=myagent, set this to match
# (or rely on the auto-pickup from TF_VAR_project_name below).
PROJECT_PREFIX = os.environ.get("TF_VAR_project_name", "gab")

ID_FILE        = pathlib.Path("deploy/.deployed_resource_id")

# Mirror the §10.2 dependency pins. These get installed in the
# managed runtime environment when the engine is created.
REQUIREMENTS = [
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


def _required(var: str) -> str:
    """Read env var or exit with a friendly error."""
    val = os.environ.get(var)
    if not val:
        sys.exit(
            f"ERROR: {var} is not set.\n"
            f"  Source your .env first: `set -a && source .env && set +a`\n"
            f"  Or export it inline: `{var}=... uv run python deploy.py`"
        )
    return val


def _existing_resource_id() -> str | None:
    if ID_FILE.exists():
        rid = ID_FILE.read_text().strip()
        if rid:
            return rid
    return None


def main() -> None:
    # Imports are lazy so missing-env errors print before the SDK eats
    # 2-3 seconds initializing.
    import vertexai
    from vertexai import agent_engines
    from google.cloud.aiplatform_v1 import types as aip_types

    project = _required("GOOGLE_CLOUD_PROJECT")
    github_org = os.environ.get("GITHUB_ORG")
    if not github_org:
        sys.exit("ERROR: GITHUB_ORG is not set. See .env.example.")
    approval_chat = os.environ.get("TELEGRAM_APPROVAL_CHAT_ID")
    if not approval_chat:
        sys.exit("ERROR: TELEGRAM_APPROVAL_CHAT_ID is not set. See .env.example.")
    sa_email = f"{PROJECT_PREFIX}-app@{project}.iam.gserviceaccount.com"
    staging_bucket = f"gs://{project}-{PROJECT_PREFIX}-staging"

    print(f"Project:        {project}", file=sys.stderr)
    print(f"Region:         {REGION}", file=sys.stderr)
    print(f"Service acct:   {sa_email}", file=sys.stderr)
    print(f"Staging bucket: {staging_bucket}", file=sys.stderr)

    vertexai.init(project=project, location=REGION, staging_bucket=staging_bucket)

    # Importing root_agent triggers loading of every LlmAgent + node — do
    # this AFTER vertexai.init so any module-level Vertex SDK calls see
    # the right project/location.
    from agent import root_agent

    # app_name MUST be a valid Python identifier — it's passed to
    # google.adk.apps.App() which calls validate_app_name(). The AdkApp
    # default is GOOGLE_CLOUD_AGENT_ENGINE_ID (a numeric string), which
    # fails .isidentifier() and crashes the runtime at startup.
    app = agent_engines.AdkApp(
        agent=root_agent,
        app_name=APP_NAME,
        enable_tracing=True,
    )

    # env_vars accepts mixed plain strings and SecretRef values per the
    # vertexai.agent_engines.create() signature.
    #
    # RESERVED VARS (auto-set by Agent Runtime, must NOT be in env_vars):
    #   - GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION
    #   - GOOGLE_GENAI_USE_VERTEXAI
    #   - GOOGLE_CLOUD_AGENT_ENGINE_ID (used by tools/memory.py to
    #     wire up Memory Bank)
    # Setting any of these returns FAILED_PRECONDITION at create time.
    env_vars = {
        "GITHUB_ORG":                github_org,
        "TELEGRAM_APPROVAL_CHAT_ID": approval_chat,
        "GCS_ASSETS_BUCKET":         f"{project}-{PROJECT_PREFIX}-assets",
        "MEMORY_BANK_BACKEND":       "vertex",
        "FIRESTORE_DATABASE":        "(default)",
        # Secret-backed env vars — values are read at runtime from
        # Secret Manager via the platform-managed sidecar.
        "GITHUB_TOKEN": aip_types.SecretRef(
            secret=f"{PROJECT_PREFIX}-github-token", version="latest"
        ),
        "TELEGRAM_BOT_TOKEN": aip_types.SecretRef(
            secret=f"{PROJECT_PREFIX}-telegram-bot-token", version="latest"
        ),
    }

    # The SDK serializes the AdkApp object but does NOT bundle the
    # source modules it imports. extra_packages ships our local package
    # dirs alongside the serialized object so the remote runtime can
    # resolve `from shared import ...` etc.
    extra_packages = [
        "agent.py",
        "shared",
        "agents",
        "nodes",
        "tools",
    ]

    existing = _existing_resource_id()
    if existing:
        print(f"\nUpdating existing engine: {existing}", file=sys.stderr)
        engine = agent_engines.get(resource_name=existing)
        engine.update(
            agent_engine=app,
            requirements=REQUIREMENTS,
            extra_packages=extra_packages,
            env_vars=env_vars,
            service_account=sa_email,
        )
    else:
        print("\nCreating new engine (this can take ~10 min)...", file=sys.stderr)
        engine = agent_engines.create(
            agent_engine=app,
            requirements=REQUIREMENTS,
            extra_packages=extra_packages,
            display_name=DISPLAY,
            description=f"{DISPLAY} — AI release → article pipeline (graph workflow + HITL)",
            env_vars=env_vars,
            service_account=sa_email,
        )

    print(f"\nResource: {engine.resource_name}")
    ID_FILE.parent.mkdir(parents=True, exist_ok=True)
    ID_FILE.write_text(engine.resource_name + "\n")
    print(f"Wrote {ID_FILE}", file=sys.stderr)


if __name__ == "__main__":
    main()
