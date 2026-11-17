variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "github_repository" {
  description = "owner/name of the repository allowed to deploy."
  type        = string
}

variable "github_environment" {
  description = "GitHub environment the deploy job must run in. Empty means any workflow of the repository."
  type        = string
  default     = ""
}

variable "repository_id" {
  description = "Artifact Registry repository the deployer pushes images to."
  type        = string
}

variable "service_names" {
  description = "Cloud Run services the deployer may update, keyed by a static label."
  type        = map(string)
}

variable "runtime_service_account_names" {
  description = "Resource names of the runtime service accounts the deployer acts as, keyed like service_names."
  type        = map(string)
}

locals {
  conditions = compact([
    "assertion.repository == '${var.github_repository}'",
    var.github_environment != "" ? "assertion.environment == '${var.github_environment}'" : "",
  ])
}

resource "google_service_account" "deployer" {
  project      = var.project_id
  account_id   = "inventory-github-deployer"
  display_name = "GitHub Actions deployer"
}

# GitHub Actions authenticates with its OIDC token: no service account key is ever created.
resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_id
  workload_identity_pool_id = "github-actions"
  display_name              = "GitHub Actions"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }

  # Only this repository (and, when set, this environment) can obtain a token.
  attribute_condition = join(" && ", local.conditions)

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_impersonates_deployer" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

resource "google_artifact_registry_repository_iam_member" "deployer_pushes_images" {
  project    = var.project_id
  location   = var.region
  repository = var.repository_id
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_cloud_run_v2_service_iam_member" "deployer_updates_service" {
  for_each = var.service_names

  project  = var.project_id
  location = var.region
  name     = each.value
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

# Deploying a revision that runs as a service account requires acting as it.
resource "google_service_account_iam_member" "deployer_acts_as_runtime" {
  for_each = var.runtime_service_account_names

  service_account_id = each.value
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

output "provider_name" {
  description = "Full resource name of the provider, for google-github-actions/auth."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_email" {
  value = google_service_account.deployer.email
}
