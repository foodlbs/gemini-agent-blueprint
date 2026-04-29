"""Structural tests for the deploy artifacts.

This file pinned the original Agent-Engine deploy contract. When the deploy
target was switched to Cloud Run via ``agents-cli scaffold enhance --
deployment-target cloud_run``, the supporting files were rewritten:
``deploy/secrets.tf`` and ``deploy/deploy.sh`` are now archived (secrets
live in Secret Manager via gcloud; deploy uses ``agents-cli deploy``), and
``deploy/scheduler.tf`` + ``deploy/cloud_function/main.py`` were rewritten
to target Cloud Run with OIDC authentication. These tests assert the
**current** contract; the archived files exist with ``.archived`` suffix
for historical reference.
"""

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEPLOY = PROJECT_ROOT / "deploy"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# --- gcs_bucket.tf (unchanged across Agent Engine -> Cloud Run migration) ----


def test_gcs_bucket_tf_declares_uniform_iam_public_read_and_90_day_lifecycle():
    """Per user spec: uniform-bucket-level-access + public-read at object
    level + 90-day lifecycle + US multi-region."""
    tf = _read(DEPLOY / "gcs_bucket.tf")
    assert 'resource "google_storage_bucket" "assets"' in tf
    assert 'resource "google_storage_bucket_iam_member" "public_read"' in tf
    assert "uniform_bucket_level_access = true" in tf
    assert 'role   = "roles/storage.objectViewer"' in tf or \
           'role = "roles/storage.objectViewer"' in tf
    assert 'member = "allUsers"' in tf
    assert "lifecycle_rule" in tf
    assert "age = 90" in tf
    assert 'type = "Delete"' in tf
    assert 'default     = "US"' in tf or 'default = "US"' in tf


# --- Cloud Run deployment via agents-cli (was: deploy.sh + Agent Engine) ----


def test_cloud_run_is_the_configured_deployment_target():
    """``agents-cli deploy`` reads the deployment target from
    pyproject.toml [tool.agents-cli.create_params]."""
    pyproject = _read(PROJECT_ROOT / "pyproject.toml")
    assert "[tool.agents-cli]" in pyproject
    assert 'deployment_target = "cloud_run"' in pyproject
    assert 'agent_directory = "app"' in pyproject


def test_app_agent_re_exports_root_agent_for_agents_cli():
    """``agents-cli deploy`` (cloud_run target) loads ``app/agent.py`` and
    expects a ``root_agent`` symbol. The actual composition lives in
    ``main.py``; ``app/agent.py`` is a thin re-export so both ``adk web``
    (``pipeline/agent.py``) and ``agents-cli`` can find the agent."""
    src = (PROJECT_ROOT / "app" / "agent.py").read_text()
    assert "root_agent" in src
    from app.agent import root_agent
    from main import root_agent as main_root_agent
    assert root_agent is main_root_agent


def test_dockerfile_copies_full_source_tree_and_installs_ffmpeg():
    """The auto-generated Dockerfile only copied ``./app``; we extended it
    so the runtime can find ``main.py`` and the agents/tools/shared trees
    that ``app/agent.py`` re-imports. ffmpeg is required by
    ``tools/video_processing.py``."""
    dockerfile = _read(PROJECT_ROOT / "Dockerfile")
    assert "ffmpeg" in dockerfile
    for path in ("./main.py", "./agents", "./tools", "./shared", "./app"):
        assert f"COPY {path}" in dockerfile, f"Dockerfile missing COPY {path}"
    assert "uv sync --frozen" in dockerfile
    assert "uvicorn" in dockerfile and "app.fast_api_app:app" in dockerfile


# --- scheduler.tf — Cloud Run target ----------------------------------------


def test_scheduler_tf_wires_scheduler_pubsub_function_chain_for_cloud_run():
    tf = _read(DEPLOY / "scheduler.tf")
    # Same four resources DESIGN.md "Deployment & triggering" requires
    assert 'resource "google_cloud_scheduler_job" "hourly"' in tf
    assert 'resource "google_pubsub_topic" "trigger"' in tf
    assert 'resource "google_cloudfunctions2_function" "trigger"' in tf
    # Hourly cron is the design's default
    assert 'default     = "0 * * * *"' in tf or 'default = "0 * * * *"' in tf
    # Scheduler publishes to the topic
    assert "pubsub_target" in tf
    # Function event-triggered by Pub/Sub
    assert "google.cloud.pubsub.topic.v1.messagePublished" in tf
    # Function env vars now point at Cloud Run, not Agent Engine
    assert "CLOUD_RUN_SERVICE_URL" in tf
    assert "AGENT_ENGINE_RESOURCE_ID" not in tf, (
        "scheduler.tf still references the old Agent Engine env var"
    )
    for var in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_CLOUD_LOCATION"):
        assert var in tf


def test_scheduler_tf_grants_run_invoker_to_function_sa():
    """Function SA needs roles/run.invoker on the Cloud Run service to call
    the --no-allow-unauthenticated endpoint; not roles/aiplatform.user (that
    was the Agent Engine path)."""
    tf = _read(DEPLOY / "scheduler.tf")
    assert 'resource "google_service_account" "function_sa"' in tf
    assert "google_cloud_run_v2_service_iam_member" in tf
    assert '"roles/run.invoker"' in tf
    # Scheduler SA still needs pubsub.publisher to push to the trigger topic.
    assert 'resource "google_service_account" "scheduler_sa"' in tf
    assert '"roles/pubsub.publisher"' in tf
    # Old Agent Engine role must be gone.
    assert "roles/aiplatform.user" not in tf


def test_scheduler_tf_creates_job_paused_by_default():
    """Per the deploy plan: do not enable the hourly cron permanently
    until the operator reviews the first manual run."""
    tf = _read(DEPLOY / "scheduler.tf")
    assert "var.scheduler_paused" in tf
    assert re.search(r"default\s*=\s*true", tf), (
        "scheduler_paused must default to true so the cron doesn't fire on first apply"
    )


def test_scheduler_job_name_matches_user_spec_for_gcloud_run():
    """User spec: ``gcloud scheduler jobs run ai-release-pipeline-hourly``."""
    tf = _read(DEPLOY / "scheduler.tf")
    assert 'name        = "ai-release-pipeline-hourly"' in tf or \
           'name = "ai-release-pipeline-hourly"' in tf


# --- cloud_function/ — calls Cloud Run via OIDC -----------------------------


def test_cloud_function_main_posts_to_cloud_run_with_oidc():
    """The function's only job is to mint an OIDC ID token and POST to the
    Cloud Run service URL. It must NOT import vertexai.agent_engines (the
    old Agent Engine path)."""
    src = _read(DEPLOY / "cloud_function" / "main.py")
    # Entry point used by terraform's google_cloudfunctions2_function
    assert "def trigger_pipeline" in src
    assert "@functions_framework.cloud_event" in src
    # OIDC token minting against the service URL audience
    assert "id_token" in src
    assert "fetch_id_token" in src
    # Reads the Cloud Run target URL terraform provisions; auth comes from
    # the metadata server so the function doesn't need to read project ID.
    assert "CLOUD_RUN_SERVICE_URL" in src
    # Hits the canonical ADK endpoints, not Agent Engine SDK
    assert "/run_sse" in src
    assert "agent_engines" not in src, "still importing the Agent Engine SDK"


def test_cloud_function_requirements_includes_functions_framework_and_auth():
    req = _read(DEPLOY / "cloud_function" / "requirements.txt")
    assert "functions-framework" in req
    assert "google-auth" in req
    assert "requests" in req
    # The Agent Engine dep should be gone.
    assert "google-cloud-aiplatform" not in req


# --- Archived legacy artifacts (kept for history; not invoked) -------------


def test_legacy_agent_engine_artifacts_are_archived_not_active():
    """Confirm the Agent-Engine-era files were not silently restored. They
    live with a ``.archived`` suffix so the original design is recoverable
    if someone wants to migrate to Agent Runtime later."""
    assert (DEPLOY / "secrets.tf.archived").exists()
    assert (DEPLOY / "deploy.sh.archived").exists()
    # And the active versions must NOT exist.
    assert not (DEPLOY / "secrets.tf").exists()
    assert not (DEPLOY / "deploy.sh").exists()


# --- pipeline/ (still used by `adk web` for local dev) ---------------------


def test_pipeline_has_requirements_for_adk_local_packaging():
    """``adk web`` and any operator running the agent locally read
    pipeline/requirements.txt to seed the venv."""
    req_path = PROJECT_ROOT / "pipeline" / "requirements.txt"
    assert req_path.exists(), "pipeline/requirements.txt missing"
    req = req_path.read_text()
    for dep in ("google-adk", "google-cloud-aiplatform", "google-cloud-storage",
                "PyGithub", "feedparser", "arxiv", "huggingface_hub",
                "python-telegram-bot", "pydantic", "ffmpeg-python", "Pillow"):
        assert dep in req, f"{dep} missing from pipeline/requirements.txt"


def test_pipeline_agent_re_exports_root_agent_for_adk_web():
    """``adk web`` discovers ``pipeline/agent.py`` and expects a
    ``root_agent`` symbol. Both ``pipeline/`` and ``app/`` re-export the
    same composition from ``main.py``."""
    src = (PROJECT_ROOT / "pipeline" / "agent.py").read_text()
    assert "root_agent" in src
    from pipeline.agent import root_agent
    from main import root_agent as main_root_agent
    assert root_agent is main_root_agent
