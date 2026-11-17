variable "project_id" {
  type = string
}

variable "notification_email" {
  description = "Where alerts are sent. Empty creates the policies without a notification channel."
  type        = string
  default     = ""
}

variable "dlq_subscription_id" {
  type = string
}

variable "push_subscription_id" {
  type = string
}

variable "cloud_run_service_names" {
  type = list(string)
}

variable "labels" {
  type    = map(string)
  default = {}
}

locals {
  channels = google_monitoring_notification_channel.email[*].id
}

resource "google_monitoring_notification_channel" "email" {
  count = var.notification_email != "" ? 1 : 0

  project      = var.project_id
  display_name = "Inventory platform alerts"
  type         = "email"
  labels = {
    email_address = var.notification_email
  }
}

resource "google_monitoring_alert_policy" "dead_letter_messages" {
  project      = var.project_id
  display_name = "Inventory: messages in the dead-letter queue"
  combiner     = "OR"
  user_labels  = var.labels

  conditions {
    display_name = "Dead-letter subscription has undelivered messages"

    condition_threshold {
      filter          = "resource.type = \"pubsub_subscription\" AND resource.labels.subscription_id = \"${var.dlq_subscription_id}\" AND metric.type = \"pubsub.googleapis.com/subscription/num_undelivered_messages\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "300s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  notification_channels = local.channels

  documentation {
    mime_type = "text/markdown"
    content   = "Events failed every delivery attempt and were moved to the dead-letter topic. Inspect them with the steps in docs/runbook.md (\"Dead-letter queue\")."
  }
}

resource "google_monitoring_alert_policy" "processor_backlog" {
  project      = var.project_id
  display_name = "Inventory: processor is falling behind"
  combiner     = "OR"
  user_labels  = var.labels

  conditions {
    display_name = "Oldest unacknowledged message is older than 10 minutes"

    condition_threshold {
      filter          = "resource.type = \"pubsub_subscription\" AND resource.labels.subscription_id = \"${var.push_subscription_id}\" AND metric.type = \"pubsub.googleapis.com/subscription/oldest_unacked_message_age\""
      comparison      = "COMPARISON_GT"
      threshold_value = 600
      duration        = "300s"

      aggregations {
        alignment_period   = "60s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  notification_channels = local.channels

  documentation {
    mime_type = "text/markdown"
    content   = "Events are waiting for the processor. Check its logs for storage errors and the BigQuery status (docs/runbook.md, \"Common problems\")."
  }
}

resource "google_monitoring_alert_policy" "cloud_run_server_errors" {
  for_each = toset(var.cloud_run_service_names)

  project      = var.project_id
  display_name = "Inventory: ${each.value} is returning 5xx"
  combiner     = "OR"
  user_labels  = var.labels

  conditions {
    display_name = "More than 5 server errors in 5 minutes"

    condition_threshold {
      filter          = "resource.type = \"cloud_run_revision\" AND resource.labels.service_name = \"${each.value}\" AND metric.type = \"run.googleapis.com/request_count\" AND metric.labels.response_code_class = \"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = 5
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
      }
    }
  }

  notification_channels = local.channels

  documentation {
    mime_type = "text/markdown"
    content   = "Look up the failing requests by trace id in Cloud Logging (docs/runbook.md, \"Diagnose a request\")."
  }
}

output "notification_channel_ids" {
  value = local.channels
}
