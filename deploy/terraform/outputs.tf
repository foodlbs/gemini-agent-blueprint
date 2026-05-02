# Outputs the operator copies into deploy.py / Cloud Run / Cloud Scheduler
# configuration after `terraform apply` succeeds. All names derived from
# var.project_name so deploy.py can reconstruct them via PROJECT_PREFIX.

output "service_account_app" {
  description = "Email of the Agent Runtime SA."
  value       = "${local.sa_app}@${var.project}.iam.gserviceaccount.com"
}

output "service_account_bridge" {
  description = "Email of the Telegram bridge Cloud Run SA."
  value       = "${local.sa_bridge}@${var.project}.iam.gserviceaccount.com"
}

output "service_account_scheduler" {
  description = "Email of the Cloud Scheduler SA."
  value       = "${local.sa_scheduler}@${var.project}.iam.gserviceaccount.com"
}

output "bucket_assets" {
  description = "Public-read GCS bucket for image/video assets."
  value       = local.bucket_assets
}

output "bucket_staging" {
  description = "GCS bucket for Vertex SDK source-tarball uploads."
  value       = local.bucket_staging
}

output "secret_github_token_id" {
  description = "Secret Manager ID for the GitHub PAT."
  value       = local.secret_github
}

output "secret_telegram_bot_token_id" {
  description = "Secret Manager ID for the Telegram bot token."
  value       = local.secret_telegram
}

output "secret_webhook_secret_id" {
  description = "Secret Manager ID for the Telegram webhook verification secret."
  value       = local.secret_webhook
}

output "telegram_webhook_secret_value" {
  description = "Plaintext value of the Telegram webhook secret (use to register the webhook with Telegram)."
  value       = random_id.webhook_secret.hex
  sensitive   = true
}

output "project_name" {
  description = "The resource-name prefix in use. Pass to deploy.py via TF_VAR_project_name or PROJECT_PREFIX."
  value       = var.project_name
}
