variable "project_id" {
  type = string
}

variable "services" {
  description = "Google APIs to enable."
  type        = list(string)
}

resource "google_project_service" "this" {
  for_each = toset(var.services)

  project = var.project_id
  service = each.value

  # Leave APIs enabled on destroy: other resources in the project may rely on them.
  disable_on_destroy = false
}
