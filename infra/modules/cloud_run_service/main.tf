variable "project_id" {
  type = string
}

variable "region" {
  type = string
}

variable "name" {
  type = string
}

variable "image" {
  description = "Initial image. CI deploys later revisions and Terraform ignores the change."
  type        = string
}

variable "service_account_email" {
  type = string
}

variable "env" {
  description = "Plain environment variables."
  type        = map(string)
  default     = {}
}

variable "secret_env" {
  description = "Environment variables read from Secret Manager."
  type = map(object({
    secret  = string
    version = string
  }))
  default = {}
}

variable "min_instances" {
  type    = number
  default = 0
}

variable "max_instances" {
  type = number
}

variable "concurrency" {
  description = "Requests per instance. Matches gunicorn's 2 workers x 8 threads."
  type        = number
  default     = 16
}

variable "cpu" {
  type    = string
  default = "1"
}

variable "memory" {
  type    = string
  default = "512Mi"
}

variable "timeout_seconds" {
  description = "Request timeout; matches the gunicorn timeout."
  type        = number
  default     = 60
}

variable "ingress" {
  type    = string
  default = "INGRESS_TRAFFIC_ALL"
}

variable "deletion_protection" {
  type = bool
}

variable "allow_unauthenticated" {
  description = "Grant roles/run.invoker to allUsers (network-level only; the app still authenticates)."
  type        = bool
  default     = false
}

variable "invoker_members" {
  description = "Service accounts allowed to invoke the service, keyed by a static label."
  type        = map(string)
  default     = {}
}

variable "labels" {
  type    = map(string)
  default = {}
}

resource "google_cloud_run_v2_service" "this" {
  project             = var.project_id
  location            = var.region
  name                = var.name
  ingress             = var.ingress
  deletion_protection = var.deletion_protection
  labels              = var.labels

  template {
    service_account                  = var.service_account_email
    timeout                          = "${var.timeout_seconds}s"
    max_instance_request_concurrency = var.concurrency

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image

      resources {
        cpu_idle = true
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }

      dynamic "env" {
        for_each = var.env
        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.secret_env
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value.secret
              version = env.value.version
            }
          }
        }
      }
    }
  }

  lifecycle {
    # The first apply runs a placeholder image; CI owns every later image.
    ignore_changes = [
      template[0].containers[0].image,
      client,
      client_version,
    ]
  }
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count = var.allow_unauthenticated ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.this.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

resource "google_cloud_run_v2_service_iam_member" "invoker" {
  for_each = var.invoker_members

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.this.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${each.value}"
}

output "name" {
  value = google_cloud_run_v2_service.this.name
}

output "uri" {
  value = google_cloud_run_v2_service.this.uri
}
