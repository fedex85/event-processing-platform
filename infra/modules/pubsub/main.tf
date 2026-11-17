variable "project_id" {
  type = string
}

variable "project_number" {
  description = "Project number, used to name the Pub/Sub service agent."
  type        = string
}

variable "topic_name" {
  type = string
}

variable "dlq_topic_name" {
  type = string
}

variable "subscription_name" {
  type = string
}

variable "push_endpoint" {
  description = "URL Pub/Sub calls: the processor's /internal/pubsub."
  type        = string
}

variable "push_audience" {
  description = "Audience of the OIDC token: the processor's base URL."
  type        = string
}

variable "push_service_account_email" {
  type = string
}

variable "push_service_account_name" {
  description = "Resource name of the push service account, to let Pub/Sub mint tokens for it."
  type        = string
}

variable "publisher_member" {
  description = "IAM member allowed to publish: the inventory-api service account."
  type        = string
}

variable "ack_deadline_seconds" {
  description = "Must cover a worst-case processing run (the gunicorn timeout is 60 s)."
  type        = number
  default     = 60
}

variable "max_delivery_attempts" {
  type    = number
  default = 5

  validation {
    condition     = var.max_delivery_attempts >= 5 && var.max_delivery_attempts <= 100
    error_message = "Pub/Sub accepts 5 to 100 delivery attempts."
  }
}

variable "labels" {
  type    = map(string)
  default = {}
}

locals {
  retention    = "604800s" # 7 days
  pubsub_agent = "serviceAccount:service-${var.project_number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_topic" "events" {
  project                    = var.project_id
  name                       = var.topic_name
  labels                     = var.labels
  message_retention_duration = local.retention
}

resource "google_pubsub_topic" "dead_letter" {
  project                    = var.project_id
  name                       = var.dlq_topic_name
  labels                     = var.labels
  message_retention_duration = local.retention
}

# Messages that exhausted their delivery attempts land here. A pull subscription keeps them
# so they can be inspected and replayed (see docs/runbook.md).
resource "google_pubsub_subscription" "dead_letter_pull" {
  project                    = var.project_id
  name                       = "${var.dlq_topic_name}-pull"
  topic                      = google_pubsub_topic.dead_letter.id
  labels                     = var.labels
  ack_deadline_seconds       = 60
  message_retention_duration = local.retention

  expiration_policy {
    ttl = "" # never expires
  }
}

resource "google_pubsub_subscription" "push" {
  project                    = var.project_id
  name                       = var.subscription_name
  topic                      = google_pubsub_topic.events.id
  labels                     = var.labels
  ack_deadline_seconds       = var.ack_deadline_seconds
  message_retention_duration = local.retention

  expiration_policy {
    ttl = "" # never expires
  }

  push_config {
    push_endpoint = var.push_endpoint

    oidc_token {
      service_account_email = var.push_service_account_email
      audience              = var.push_audience
    }
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = var.max_delivery_attempts
  }

  depends_on = [
    google_pubsub_topic_iam_member.dead_letter_publisher,
    google_service_account_iam_member.agent_mints_push_tokens,
  ]
}

resource "google_pubsub_topic_iam_member" "api_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.events.name
  role    = "roles/pubsub.publisher"
  member  = var.publisher_member
}

# For dead-lettering, the Pub/Sub service agent publishes to the DLQ topic and acknowledges
# on the source subscription. If the first apply fails because the agent does not exist yet,
# run: gcloud beta services identity create --service=pubsub.googleapis.com
resource "google_pubsub_topic_iam_member" "dead_letter_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.dead_letter.name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_agent
}

resource "google_pubsub_subscription_iam_member" "dead_letter_subscriber" {
  project      = var.project_id
  subscription = google_pubsub_subscription.push.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_agent
}

# Lets Pub/Sub sign the OIDC token Cloud Run IAM checks.
resource "google_service_account_iam_member" "agent_mints_push_tokens" {
  service_account_id = var.push_service_account_name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = local.pubsub_agent
}

output "topic_name" {
  value = google_pubsub_topic.events.name
}

output "dlq_topic_name" {
  value = google_pubsub_topic.dead_letter.name
}

output "push_subscription_name" {
  value = google_pubsub_subscription.push.name
}

output "dlq_subscription_name" {
  value = google_pubsub_subscription.dead_letter_pull.name
}
