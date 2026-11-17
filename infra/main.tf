provider "google" {
  project = var.project_id
  region  = var.region
}

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  api_service_name       = "inventory-api"
  processor_service_name = "inventory-processor"
  topic_name             = "stock-events"
  dlq_topic_name         = "stock-events-dlq"
  subscription_name      = "stock-events-processor"
  api_keys_secret_id     = "inventory-api-keys"

  labels = {
    app         = "inventory-event-platform"
    environment = var.environment
    managed_by  = "terraform"
  }

  common_env = {
    ENVIRONMENT    = var.environment
    GCP_PROJECT_ID = var.project_id
    BQ_DATASET     = var.bq_dataset_id
    LOG_LEVEL      = "INFO"
  }
}

module "apis" {
  source     = "./modules/apis"
  project_id = var.project_id
  services = [
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "sts.googleapis.com",
    "cloudtrace.googleapis.com",
  ]
}

module "service_accounts" {
  source     = "./modules/service_accounts"
  project_id = var.project_id

  depends_on = [module.apis]
}

module "artifact_registry" {
  source        = "./modules/artifact_registry"
  project_id    = var.project_id
  region        = var.region
  repository_id = "inventory"
  labels        = local.labels

  depends_on = [module.apis]
}

module "secrets" {
  source          = "./modules/secrets"
  project_id      = var.project_id
  secret_id       = local.api_keys_secret_id
  accessor_member = "serviceAccount:${module.service_accounts.api_email}"
  labels          = local.labels

  depends_on = [module.apis]
}

module "bigquery" {
  source              = "./modules/bigquery"
  project_id          = var.project_id
  dataset_id          = var.bq_dataset_id
  location            = var.bq_location
  deletion_protection = var.deletion_protection
  events_schema_file  = "${path.module}/schemas/stock_events.json"
  alerts_schema_file  = "${path.module}/schemas/stock_alerts.json"
  view_query_file     = "${path.module}/sql/v_stock_trends.sql"
  reader_member       = "serviceAccount:${module.service_accounts.api_email}"
  writer_member       = "serviceAccount:${module.service_accounts.processor_email}"
  labels              = local.labels

  depends_on = [module.apis]
}

module "api_service" {
  source                = "./modules/cloud_run_service"
  project_id            = var.project_id
  region                = var.region
  name                  = local.api_service_name
  image                 = var.api_image
  service_account_email = module.service_accounts.api_email
  max_instances         = var.api_max_instances
  deletion_protection   = var.deletion_protection
  allow_unauthenticated = var.api_public
  labels                = local.labels

  env = merge(local.common_env, {
    PUBSUB_TOPIC_ID = local.topic_name
  })
  secret_env = {
    API_KEYS = {
      secret  = module.secrets.secret_id
      version = "latest"
    }
  }

  depends_on = [module.apis, module.secrets]
}

module "processor_service" {
  source                = "./modules/cloud_run_service"
  project_id            = var.project_id
  region                = var.region
  name                  = local.processor_service_name
  image                 = var.processor_image
  service_account_email = module.service_accounts.processor_email
  max_instances         = var.processor_max_instances
  deletion_protection   = var.deletion_protection
  allow_unauthenticated = false
  labels                = local.labels
  env                   = local.common_env

  # Only the Pub/Sub push subscription may call the processor.
  invoker_members = {
    pubsub_push = module.service_accounts.pubsub_push_email
  }

  depends_on = [module.apis]
}

module "pubsub" {
  source                     = "./modules/pubsub"
  project_id                 = var.project_id
  project_number             = data.google_project.this.number
  topic_name                 = local.topic_name
  dlq_topic_name             = local.dlq_topic_name
  subscription_name          = local.subscription_name
  push_endpoint              = "${module.processor_service.uri}/internal/pubsub"
  push_audience              = module.processor_service.uri
  push_service_account_email = module.service_accounts.pubsub_push_email
  push_service_account_name  = module.service_accounts.pubsub_push_name
  publisher_member           = "serviceAccount:${module.service_accounts.api_email}"
  max_delivery_attempts      = var.max_delivery_attempts
  labels                     = local.labels

  depends_on = [module.apis]
}

module "github_wif" {
  count  = var.github_repository != "" ? 1 : 0
  source = "./modules/github_wif"

  project_id         = var.project_id
  github_repository  = var.github_repository
  github_environment = var.github_environment
  repository_id      = module.artifact_registry.repository_id
  region             = var.region
  service_names = {
    api       = module.api_service.name
    processor = module.processor_service.name
  }
  runtime_service_account_names = {
    api       = module.service_accounts.api_name
    processor = module.service_accounts.processor_name
  }

  depends_on = [module.apis]
}

module "monitoring" {
  source                  = "./modules/monitoring"
  project_id              = var.project_id
  notification_email      = var.alert_email
  dlq_subscription_id     = module.pubsub.dlq_subscription_name
  push_subscription_id    = module.pubsub.push_subscription_name
  cloud_run_service_names = [local.api_service_name, local.processor_service_name]
  labels                  = local.labels

  depends_on = [module.apis]
}
