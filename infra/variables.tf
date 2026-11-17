variable "project_id" {
  description = "GCP project that hosts this environment (one project per environment is recommended)."
  type        = string
}

variable "environment" {
  description = "Environment name; also the ENVIRONMENT value the services run with."
  type        = string

  validation {
    condition     = contains(["staging", "prod"], var.environment)
    error_message = "environment must be \"staging\" or \"prod\"."
  }
}

variable "region" {
  description = "Region for Cloud Run and Artifact Registry."
  type        = string
  default     = "europe-southwest1"
}

variable "bq_location" {
  description = "BigQuery dataset location (a region or a multi-region such as EU)."
  type        = string
  default     = "EU"
}

variable "bq_dataset_id" {
  description = "BigQuery dataset id; must match the services' BQ_DATASET."
  type        = string
  default     = "inventory_analytics"
}

variable "deletion_protection" {
  description = "Protect BigQuery tables and Cloud Run services from terraform destroy. Keep true in prod."
  type        = bool
  default     = true
}

variable "api_public" {
  description = "Let anyone reach inventory-api at the network level (clients still need an API key). Set false if an organization policy forbids allUsers."
  type        = bool
  default     = true
}

variable "api_max_instances" {
  description = "Upper bound for inventory-api instances; also bounds the cost of a traffic spike."
  type        = number
  default     = 10
}

variable "processor_max_instances" {
  description = "Upper bound for inventory-processor instances; also bounds BigQuery write pressure."
  type        = number
  default     = 10
}

variable "api_image" {
  description = "Initial image for inventory-api. CI deploys the real image afterwards and Terraform ignores later changes."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "processor_image" {
  description = "Initial image for inventory-processor. CI deploys the real image afterwards and Terraform ignores later changes."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "max_delivery_attempts" {
  description = "Delivery attempts before Pub/Sub moves a message to the dead-letter topic (5 to 100)."
  type        = number
  default     = 5
}

variable "github_repository" {
  description = "GitHub repository (owner/name) allowed to deploy through Workload Identity Federation. Leave empty to skip creating it."
  type        = string
  default     = ""
}

variable "github_environment" {
  description = "GitHub environment name the deploy job runs in (for example staging or production). When set, only jobs in that environment can authenticate."
  type        = string
  default     = ""
}

variable "alert_email" {
  description = "Email that receives monitoring alerts. Leave empty to create the alert policies without a notification channel."
  type        = string
  default     = ""
}
