# Outputs the operator copies into deploy.py / Cloud Run / Cloud Scheduler
# configuration after `terraform apply` succeeds.

output "service_account_app" {
  description = "Email of the Agent Runtime runtime SA — passed to deploy.py."
  value       = google_service_account.app.email
}

output "service_account_bridge" {
  description = "Email of the Telegram bridge Cloud Run SA."
  value       = google_service_account.bridge.email
}

output "service_account_scheduler" {
  description = "Email of the Cloud Scheduler OIDC SA."
  value       = google_service_account.scheduler.email
}

output "assets_bucket" {
  description = "GCS bucket for image/video asset hosting."
  value       = google_storage_bucket.assets.name
}

output "staging_bucket" {
  description = "GCS bucket for Vertex AI source tarball uploads (deploy.py)."
  value       = google_storage_bucket.staging.name
}

output "secret_github_token_id" {
  description = "Resource ID of the GitHub PAT secret."
  value       = google_secret_manager_secret.github_token.id
}

output "secret_telegram_bot_token_id" {
  description = "Resource ID of the Telegram bot token secret."
  value       = google_secret_manager_secret.telegram_bot_token.id
}

output "secret_telegram_webhook_secret_id" {
  description = "Resource ID of the Telegram webhook secret."
  value       = google_secret_manager_secret.telegram_webhook_secret.id
}

output "telegram_webhook_secret_value" {
  description = <<-EOT
    Generated webhook-verification token (32 random bytes hex).
    Telegram echoes this on every webhook call. Used in setWebhook
    after the bridge is deployed (see README.md).
  EOT
  value     = random_id.webhook_secret.hex
  sensitive = true
}
