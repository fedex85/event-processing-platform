variable "project_id" {
  type = string
}

variable "secret_id" {
  type = string
}

variable "accessor_member" {
  description = "IAM member allowed to read the secret: the inventory-api service account."
  type        = string
}

variable "labels" {
  type    = map(string)
  default = {}
}

# Only the secret container is managed here. Its value (the API keys) is added by hand as a
# version, so it never appears in Terraform state or in the repository.
resource "google_secret_manager_secret" "api_keys" {
  project   = var.project_id
  secret_id = var.secret_id
  labels    = var.labels

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "accessor" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.api_keys.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = var.accessor_member
}

output "secret_id" {
  value = google_secret_manager_secret.api_keys.secret_id
}
