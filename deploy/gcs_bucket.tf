# GCS bucket for AI release pipeline assets (images, videos, GIFs, posters).
# Public-read at the object level via uniform IAM; 90-day lifecycle.

variable "gcs_assets_bucket" {
  description = "Name of the GCS bucket for AI release pipeline assets."
  type        = string
}

variable "gcs_location" {
  description = "Bucket location (multi-region or region)."
  type        = string
  default     = "US"
}

resource "google_storage_bucket" "assets" {
  name                        = var.gcs_assets_bucket
  location                    = var.gcs_location
  storage_class               = "STANDARD"
  force_destroy               = false
  uniform_bucket_level_access = true

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }
}

# Grant public read access to all objects in the bucket.
resource "google_storage_bucket_iam_member" "public_read" {
  bucket = google_storage_bucket.assets.name
  role   = "roles/storage.objectViewer"
  member = "allUsers"
}

output "assets_bucket_name" {
  description = "Bucket name to set as GCS_ASSETS_BUCKET in the runtime env."
  value       = google_storage_bucket.assets.name
}

output "assets_bucket_url" {
  description = "Base URL where uploaded objects are publicly reachable."
  value       = "https://storage.googleapis.com/${google_storage_bucket.assets.name}"
}
