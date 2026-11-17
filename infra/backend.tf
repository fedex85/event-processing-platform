# Remote state in a versioned GCS bucket. The bucket and the per-environment prefix are
# passed at init time so nothing about a project is hardcoded here:
#
#   terraform init -backend-config="bucket=<state-bucket>" -backend-config="prefix=staging"
terraform {
  backend "gcs" {}
}
