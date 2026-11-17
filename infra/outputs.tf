output "api_url" {
  description = "Base URL of inventory-api."
  value       = module.api_service.uri
}

output "processor_url" {
  description = "Base URL of inventory-processor (not publicly invokable)."
  value       = module.processor_service.uri
}

output "artifact_registry_url" {
  description = "Docker repository CI pushes images to."
  value       = module.artifact_registry.repository_url
}

output "pubsub_topic" {
  description = "Topic inventory-api publishes to."
  value       = module.pubsub.topic_name
}

output "dead_letter_subscription" {
  description = "Pull subscription to inspect messages that failed repeatedly."
  value       = module.pubsub.dlq_subscription_name
}

output "bigquery_dataset" {
  description = "Dataset holding stock_events, stock_alerts and v_stock_trends."
  value       = module.bigquery.dataset_id
}

output "api_keys_secret" {
  description = "Secret Manager secret holding the comma-separated API keys. Add its first version by hand."
  value       = module.secrets.secret_id
}

output "github_workload_identity_provider" {
  description = "Value for the GCP_WORKLOAD_IDENTITY_PROVIDER GitHub variable."
  value       = one(module.github_wif[*].provider_name)
}

output "github_deployer_service_account" {
  description = "Value for the GCP_DEPLOYER_SERVICE_ACCOUNT GitHub variable."
  value       = one(module.github_wif[*].deployer_email)
}
