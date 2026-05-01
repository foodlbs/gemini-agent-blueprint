# Service accounts + IAM bindings for ai-release-pipeline-v2.
# DESIGN.v2.md §10.3.
#
# Three SAs, one per long-lived resource (all derived from var.project_name):
#   - ${var.project_name}-app             → Agent Runtime ReasoningEngine
#   - ${var.project_name}-telegram-bridge → Cloud Run service
#   - ${var.project_name}-scheduler       → Cloud Scheduler jobs
#
# Bindings on resources NOT in this module (Memory Bank, the engine
# itself, the bridge Cloud Run) are documented in README.md as
# post-create steps.

# ---------------------------------------------------------------------------
# Service accounts
# ---------------------------------------------------------------------------

resource "google_service_account" "app" {
  account_id   = local.sa_app
  display_name = "AI Release Pipeline v2 — Agent Runtime"
  description  = "Runtime SA for the v2 ReasoningEngine. DESIGN.v2.md §10.3."
}

resource "google_service_account" "bridge" {
  account_id   = local.sa_bridge
  display_name = "AI Release Pipeline v2 — Telegram Bridge"
  description  = "Cloud Run runtime SA for the Telegram webhook bridge. DESIGN.v2.md §10.3."
}

resource "google_service_account" "scheduler" {
  account_id   = local.sa_scheduler
  display_name = "AI Release Pipeline v2 — Cloud Scheduler"
  description  = "OIDC token issuer for hourly cron + 15-min sweeper. DESIGN.v2.md §10.3."
}

# ---------------------------------------------------------------------------
# app SA (local.sa_app) — Agent Runtime runtime SA
# ---------------------------------------------------------------------------

# Project-level: Vertex AI (Gemini, Imagen, Veo, Memory Bank API), Firestore,
# log writing, Cloud Trace export.
resource "google_project_iam_member" "app_aiplatform_user" {
  project = var.project
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.app.email}"
}

resource "google_project_iam_member" "app_datastore_user" {
  project = var.project
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.app.email}"
}

resource "google_project_iam_member" "app_logging_log_writer" {
  project = var.project
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.app.email}"
}

resource "google_project_iam_member" "app_cloudtrace_agent" {
  project = var.project
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.app.email}"
}

# Required for the SA to CALL Google APIs from within the project
# (storage.googleapis.com, etc.). Storage's resource-level objectAdmin
# permits the operation but Google's API gateway also enforces a
# project-level "are you allowed to use this service?" check, which
# returns 403 with `serviceusage.services.use denied` if missing.
resource "google_project_iam_member" "app_serviceusage_consumer" {
  project = var.project
  role    = "roles/serviceusage.serviceUsageConsumer"
  member  = "serviceAccount:${google_service_account.app.email}"
}

# Resource-level: assets bucket (read+write), staging bucket (Vertex
# SDK uploads source tarball there during deploy.py).
resource "google_storage_bucket_iam_member" "app_assets_admin" {
  bucket = google_storage_bucket.assets.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.app.email}"
}

resource "google_storage_bucket_iam_member" "app_staging_admin" {
  bucket = google_storage_bucket.staging.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.app.email}"
}

# Per-secret accessor — the app reads two secrets at runtime via the
# secret_environment_variables sidecar mount in deploy.py.
resource "google_secret_manager_secret_iam_member" "app_github_token" {
  secret_id = google_secret_manager_secret.github_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

resource "google_secret_manager_secret_iam_member" "app_telegram_bot_token" {
  secret_id = google_secret_manager_secret.telegram_bot_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.app.email}"
}

# NOTE — Memory Bank IAM:
# In ADK 2.0b1, Memory Bank is an API surface on the ReasoningEngine
# itself (calls go to /reasoningEngines/{id}/memories) — there is no
# separate Memory Bank instance and `roles/aiplatform.memoryBankUser`
# is not a bindable role here. The project-level `aiplatform.user`
# above covers Memory Bank API access. See README.md for details.

# ---------------------------------------------------------------------------
# bridge SA (local.sa_bridge) — Cloud Run runtime SA
# ---------------------------------------------------------------------------

resource "google_project_iam_member" "bridge_aiplatform_user" {
  project = var.project
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.bridge.email}"
}

resource "google_project_iam_member" "bridge_datastore_user" {
  project = var.project
  role    = "roles/datastore.user"
  member  = "serviceAccount:${google_service_account.bridge.email}"
}

resource "google_project_iam_member" "bridge_logging_log_writer" {
  project = var.project
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.bridge.email}"
}

resource "google_secret_manager_secret_iam_member" "bridge_telegram_bot_token" {
  secret_id = google_secret_manager_secret.telegram_bot_token.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.bridge.email}"
}

resource "google_secret_manager_secret_iam_member" "bridge_webhook_secret" {
  secret_id = google_secret_manager_secret.telegram_webhook_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.bridge.email}"
}

# NOTE — engine-scoped binding:
# `roles/aiplatform.reasoningEngineUser` on the v2 engine is more
# granular than aiplatform.user (project-wide), but the engine isn't
# provisioned by Terraform yet. The project-wide aiplatform.user above
# is sufficient until then. README.md tracks the optional tightening.

# ---------------------------------------------------------------------------
# scheduler SA (local.sa_scheduler) — Cloud Scheduler OIDC SA
# ---------------------------------------------------------------------------

# The scheduler SA only needs project-wide aiplatform.user to call
# :streamQuery on the v2 engine, AND run.invoker on the bridge Cloud
# Run for the sweeper job. Both are bound after the targets exist —
# see README.md.
#
# We pre-create the SA here so downstream Cloud Scheduler jobs can
# reference its email without a chicken-and-egg dependency on Terraform.
