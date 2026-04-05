terraform {
  required_providers {
    google = { source = "hashicorp/google"; version = "~> 5.0" }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_cloud_run_v2_service" "app" {
  name     = var.app_name
  location = var.region

  template {
    containers {
      image = var.docker_image
      ports { container_port = 8000 }
      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }
      env {
        name  = "ENVIRONMENT"
        value = var.environment
      }
    }

    scaling {
      min_instance_count = var.min_replicas
      max_instance_count = var.max_replicas
    }
  }

  labels = {
    environment = var.environment
    managed-by  = "devtodeploy"
  }
}

# Allow unauthenticated access
resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.app.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
