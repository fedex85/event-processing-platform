variable "project_id" {
  type = string
}

resource "google_service_account" "api" {
  project      = var.project_id
  account_id   = "inventory-api"
  display_name = "inventory-api runtime"
}

resource "google_service_account" "processor" {
  project      = var.project_id
  account_id   = "inventory-processor"
  display_name = "inventory-processor runtime"
}

resource "google_service_account" "pubsub_push" {
  project      = var.project_id
  account_id   = "inventory-pubsub-push"
  display_name = "Pub/Sub push subscription (invokes the processor)"
}

# Both services run BigQuery queries. Table access comes from dataset-level grants in the
# bigquery module; publishing and secret access are granted on the topic and the secret.
resource "google_project_iam_member" "api_bigquery_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.api.email}"
}

resource "google_project_iam_member" "processor_bigquery_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.processor.email}"
}

output "api_email" {
  value = google_service_account.api.email
}

output "api_name" {
  value = google_service_account.api.name
}

output "processor_email" {
  value = google_service_account.processor.email
}

output "processor_name" {
  value = google_service_account.processor.name
}

output "pubsub_push_email" {
  value = google_service_account.pubsub_push.email
}

output "pubsub_push_name" {
  value = google_service_account.pubsub_push.name
}
