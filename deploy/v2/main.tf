# Terraform module for ai-release-pipeline-v2 supporting infrastructure.
# DESIGN.v2.md §10.3 + §10.4. Provisions:
#   - 2 GCS buckets (assets + Vertex staging)
#   - 3 Secret Manager secrets (github, telegram bot, webhook)
#   - random_id-generated webhook secret value
#
# Service accounts and IAM bindings live in iam.tf (split for readability).
#
# Memory Bank instance is NOT in this module — see README.md for the
# gcloud + import workflow (§15 Q2).
#
# State: local terraform.tfstate. Migrate to a GCS backend when more
# than one operator manages this infrastructure.

terraform {
  required_version = ">= 1.6"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "google" {
  project = var.project
  region  = var.region
}

# ---------------------------------------------------------------------------
# Variables
# ---------------------------------------------------------------------------

variable "project_name" {
  description = "Resource-name prefix shared with deploy.py (PROJECT_PREFIX env var). Drives SA names, secret names, bucket names. Default 'gab' = gemini-agent-blueprint."
  type        = string
  default     = "gab"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,28}$", var.project_name))
    error_message = "project_name must be 2-29 chars, lowercase letters/digits/hyphens, starting with a letter."
  }
}

variable "project" {
  description = "GCP project ID (e.g. gen-lang-client-0366435980)."
  type        = string
}

variable "region" {
  description = "GCP region. Pinned to us-west1 per DESIGN.v2.md §3."
  type        = string
  default     = "us-west1"
}

variable "github_token" {
  description = <<-EOT
    GitHub PAT with `repo` scope (no `delete_repo`). Pass via:
      export TF_VAR_github_token=ghp_xxxx
    Never commit the value or pass it on the command line (shell history).
  EOT
  type      = string
  sensitive = true
}

variable "telegram_bot_token" {
  description = <<-EOT
    Telegram bot token from @BotFather. Pass via:
      export TF_VAR_telegram_bot_token=8015575416:AAH...
  EOT
  type      = string
  sensitive = true
}

# ---------------------------------------------------------------------------
# Derived names — single source of truth shared by deploy.py via
# PROJECT_PREFIX / TF_VAR_project_name. Patterns must match deploy.py.
# ---------------------------------------------------------------------------

locals {
  sa_app          = "${var.project_name}-app"
  sa_bridge       = "${var.project_name}-telegram-bridge"
  sa_scheduler    = "${var.project_name}-scheduler"
  secret_github   = "${var.project_name}-github-token"
  secret_telegram = "${var.project_name}-telegram-bot-token"
  secret_webhook  = "${var.project_name}-telegram-webhook-secret"
  bucket_assets   = "${var.project}-${var.project_name}-assets"
  bucket_staging  = "${var.project}-${var.project_name}-staging"
}

# ---------------------------------------------------------------------------
# GCS — assets bucket (public-read, 90-day lifecycle)
# ---------------------------------------------------------------------------

resource "google_storage_bucket" "assets" {
  name                        = local.bucket_assets
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  # Refuse `terraform destroy` — published article assets must not vanish
  # when someone runs `terraform destroy` by mistake.
  force_destroy = false

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }
}

# Public-read on the assets bucket so rendered Markdown URLs resolve
# directly. allUsers + objectViewer is the documented uniform-IAM pattern.
resource "google_storage_bucket_iam_member" "assets_public_read" {
  bucket = google_storage_bucket.assets.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

# ---------------------------------------------------------------------------
# GCS — Vertex AI staging bucket (source tarball uploads from deploy.py)
# ---------------------------------------------------------------------------

resource "google_storage_bucket" "staging" {
  name                        = local.bucket_staging
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  # Staging is ephemeral — Vertex SDK rotates source tarballs there.
  # Safe to allow `terraform destroy` to reclaim it.
  force_destroy = true
}

# ---------------------------------------------------------------------------
# Secret Manager — three secrets per §10.4
# ---------------------------------------------------------------------------

resource "google_secret_manager_secret" "github_token" {
  secret_id = local.secret_github

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

resource "google_secret_manager_secret_version" "github_token" {
  secret      = google_secret_manager_secret.github_token.id
  secret_data = var.github_token
}

resource "google_secret_manager_secret" "telegram_bot_token" {
  secret_id = local.secret_telegram

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

resource "google_secret_manager_secret_version" "telegram_bot_token" {
  secret      = google_secret_manager_secret.telegram_bot_token.id
  secret_data = var.telegram_bot_token
}

# Webhook secret — Telegram echoes this back on every webhook call so
# the bridge can verify the request actually came from Telegram.
# Generated by Terraform; rotated by `terraform apply -replace=random_id.webhook_secret`.
resource "random_id" "webhook_secret" {
  byte_length = 32
}

resource "google_secret_manager_secret" "telegram_webhook_secret" {
  secret_id = local.secret_webhook

  replication {
    user_managed {
      replicas {
        location = var.region
      }
    }
  }
}

resource "google_secret_manager_secret_version" "telegram_webhook_secret" {
  secret      = google_secret_manager_secret.telegram_webhook_secret.id
  secret_data = random_id.webhook_secret.hex
}
