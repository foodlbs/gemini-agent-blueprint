# Hourly trigger pipeline:
#   Cloud Scheduler (cron) -> Pub/Sub -> Cloud Function (Gen2) -> Cloud Run.
#
# Cloud Scheduler publishes a message to Pub/Sub each hour. The Cloud
# Function consumes the message and POSTs to the Cloud Run service URL with
# an OIDC ID token (the service is deployed --no-allow-unauthenticated). The
# function drains the first few SSE events to confirm the pipeline started,
# then closes the connection; Cloud Run continues handling the request until
# the configured request timeout (15 min on the current deploy).
#
# DEVIATION FROM DESIGN.md: The original design pointed at Agent Engine,
# which natively supports 24-hour detached runs. We're on Cloud Run via
# `agents-cli deploy --deployment-target cloud_run`; that caps requests at
# 60 minutes (we set 15 min). If a Telegram approval takes longer than the
# request timeout, the pipeline will be killed mid-run.

terraform {
  required_providers {
    google = { source = "hashicorp/google" }
    archive = { source = "hashicorp/archive" }
  }
}

provider "google" {
  project = var.google_cloud_project
  region  = var.google_cloud_location
}

variable "google_cloud_project" {
  type        = string
  description = "GCP project ID."
}

variable "google_cloud_location" {
  type        = string
  description = "GCP region (e.g., us-east1, us-central1)."
  default     = "us-east1"
}

variable "cloud_run_service_url" {
  type        = string
  description = "Public URL of the deployed Cloud Run service (e.g. https://ai-release-pipeline-988979702911.us-east1.run.app). Capture this from `agents-cli deploy` output."
}

variable "cloud_run_service_name" {
  type        = string
  description = "Cloud Run service name (e.g. ai-release-pipeline). Used for IAM binding."
  default     = "ai-release-pipeline"
}

variable "polling_cron" {
  type        = string
  description = "Cron schedule for the hourly trigger."
  default     = "0 * * * *"
}

variable "scheduler_paused" {
  type        = bool
  description = "If true, the Scheduler job is created in PAUSED state. Toggle to false to enable hourly runs."
  default     = true
}

# --- Pub/Sub topic ---------------------------------------------------------

resource "google_pubsub_topic" "trigger" {
  name = "ai-release-pipeline-trigger"
}

# --- Cloud Function source bucket -----------------------------------------

resource "google_storage_bucket" "function_source" {
  name                        = "${var.google_cloud_project}-airel-fn-source"
  location                    = var.google_cloud_location
  uniform_bucket_level_access = true
  force_destroy               = true
}

data "archive_file" "function_zip" {
  type        = "zip"
  source_dir  = "${path.module}/cloud_function"
  output_path = "${path.module}/.terraform/cloud_function.zip"
}

resource "google_storage_bucket_object" "function_zip" {
  name   = "trigger-${data.archive_file.function_zip.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.function_zip.output_path
}

# --- Service accounts -----------------------------------------------------

resource "google_service_account" "function_sa" {
  account_id   = "ai-release-pipeline-fn"
  display_name = "AI release pipeline function trigger"
  description  = "Service account for the Cloud Function that POSTs to Cloud Run."
}

# Allow the function SA to invoke the Cloud Run service.
resource "google_cloud_run_v2_service_iam_member" "function_sa_invoker" {
  project  = var.google_cloud_project
  location = var.google_cloud_location
  name     = var.cloud_run_service_name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.function_sa.email}"
}

resource "google_service_account" "scheduler_sa" {
  account_id   = "ai-release-pipeline-sched"
  display_name = "AI release pipeline scheduler"
  description  = "Service account for the Cloud Scheduler hourly trigger."
}

resource "google_project_iam_member" "scheduler_sa_pubsub_publisher" {
  project = var.google_cloud_project
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.scheduler_sa.email}"
}

# --- Cloud Function (Gen2) -------------------------------------------------

resource "google_cloudfunctions2_function" "trigger" {
  name     = "ai-release-pipeline-trigger"
  location = var.google_cloud_location

  build_config {
    runtime     = "python312"
    entry_point = "trigger_pipeline"
    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.function_zip.name
      }
    }
  }

  service_config {
    max_instance_count    = 4
    min_instance_count    = 0
    available_memory      = "512M"
    timeout_seconds       = 540
    service_account_email = google_service_account.function_sa.email
    environment_variables = {
      GOOGLE_CLOUD_PROJECT     = var.google_cloud_project
      GOOGLE_CLOUD_LOCATION    = var.google_cloud_location
      CLOUD_RUN_SERVICE_URL    = var.cloud_run_service_url
      APP_NAME                 = "app"
    }
  }

  event_trigger {
    trigger_region = var.google_cloud_location
    event_type     = "google.cloud.pubsub.topic.v1.messagePublished"
    pubsub_topic   = google_pubsub_topic.trigger.id
    retry_policy   = "RETRY_POLICY_DO_NOT_RETRY"
  }
}

# --- Cloud Scheduler hourly cron ------------------------------------------
#
# Created PAUSED by default (var.scheduler_paused = true) so the hourly run
# does not fire automatically until the operator reviews the first manual
# trigger. Toggle to false (or run `gcloud scheduler jobs resume <name>`)
# when ready to go live.

resource "google_cloud_scheduler_job" "hourly" {
  name        = "ai-release-pipeline-hourly"
  description = "Hourly trigger for the AI release pipeline (DESIGN.md Deployment & triggering)."
  schedule    = var.polling_cron
  time_zone   = "UTC"
  region      = var.google_cloud_location
  paused      = var.scheduler_paused

  pubsub_target {
    topic_name = google_pubsub_topic.trigger.id
    data       = base64encode(jsonencode({ source = "scheduler", trigger = "hourly" }))
  }

  retry_config {
    retry_count = 1
  }
}

# --- Outputs ---------------------------------------------------------------

output "scheduler_job_name" {
  description = "Run with: gcloud scheduler jobs run <name> --location=<region>"
  value       = google_cloud_scheduler_job.hourly.name
}

output "scheduler_paused" {
  description = "Whether the Scheduler job was created in PAUSED state."
  value       = google_cloud_scheduler_job.hourly.paused
}

output "function_name" {
  value = google_cloudfunctions2_function.trigger.name
}

output "trigger_topic" {
  value = google_pubsub_topic.trigger.name
}

output "function_sa_email" {
  description = "Service account that the Cloud Function uses to invoke Cloud Run."
  value       = google_service_account.function_sa.email
}
