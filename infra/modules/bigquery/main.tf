variable "project_id" {
  type = string
}

variable "dataset_id" {
  type = string
}

variable "location" {
  type = string
}

variable "deletion_protection" {
  type = bool
}

variable "events_schema_file" {
  type = string
}

variable "alerts_schema_file" {
  type = string
}

variable "view_query_file" {
  description = "SQL of v_stock_trends with $${project_id} and $${dataset} placeholders."
  type        = string
}

variable "reader_member" {
  description = "IAM member (for example serviceAccount:...) that reads the dataset: inventory-api."
  type        = string
}

variable "writer_member" {
  description = "IAM member that writes events and alerts: inventory-processor."
  type        = string
}

variable "labels" {
  type    = map(string)
  default = {}
}

resource "google_bigquery_dataset" "this" {
  project       = var.project_id
  dataset_id    = var.dataset_id
  location      = var.location
  friendly_name = "Inventory analytics"
  description   = "Stock events, alerts and trends produced by the inventory event platform."
  labels        = var.labels

  delete_contents_on_destroy = false
}

# Partitioned by the event's own time and clustered by the columns every query filters on,
# so lookups and reads scan only the days and stores they need.
resource "google_bigquery_table" "stock_events" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.this.dataset_id
  table_id            = "stock_events"
  description         = "One row per processed stock event."
  labels              = var.labels
  deletion_protection = var.deletion_protection
  schema              = file(var.events_schema_file)

  time_partitioning {
    type  = "DAY"
    field = "occurred_at"
  }

  clustering = ["store_id", "sku"]
}

resource "google_bigquery_table" "stock_alerts" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.this.dataset_id
  table_id            = "stock_alerts"
  description         = "Alerts raised by the processor's rules."
  labels              = var.labels
  deletion_protection = var.deletion_protection
  schema              = file(var.alerts_schema_file)

  time_partitioning {
    type  = "DAY"
    field = "detected_at"
  }

  clustering = ["store_id", "sku"]
}

resource "google_bigquery_table" "v_stock_trends" {
  project             = var.project_id
  dataset_id          = google_bigquery_dataset.this.dataset_id
  table_id            = "v_stock_trends"
  description         = "Hourly sales, restocks, average stock and variation per store and SKU."
  labels              = var.labels
  deletion_protection = false

  view {
    use_legacy_sql = false
    query = templatefile(var.view_query_file, {
      project_id = var.project_id
      dataset    = google_bigquery_dataset.this.dataset_id
    })
  }

  depends_on = [google_bigquery_table.stock_events]
}

# Least privilege: the API only reads (the view reads stock_events through the same grant);
# the processor only appends.
resource "google_bigquery_dataset_iam_member" "reader" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.this.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = var.reader_member
}

resource "google_bigquery_dataset_iam_member" "writer" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.this.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = var.writer_member
}

output "dataset_id" {
  value = google_bigquery_dataset.this.dataset_id
}

output "events_table_id" {
  value = google_bigquery_table.stock_events.table_id
}

output "alerts_table_id" {
  value = google_bigquery_table.stock_alerts.table_id
}

output "view_id" {
  value = google_bigquery_table.v_stock_trends.table_id
}
