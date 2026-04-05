terraform {
  required_providers {
    google = { source = "hashicorp/google"; version = "~> 5.0" }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

resource "google_container_cluster" "gke" {
  name     = "${var.app_name}-gke"
  location = var.region

  remove_default_node_pool = true
  initial_node_count       = 1

  deletion_protection = false

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }
}

resource "google_container_node_pool" "nodes" {
  name       = "default-pool"
  location   = var.region
  cluster    = google_container_cluster.gke.name

  node_count = var.node_count

  autoscaling {
    min_node_count = var.min_replicas
    max_node_count = var.max_replicas
  }

  node_config {
    machine_type = var.machine_type
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
    ]
    labels = {
      environment = var.environment
    }
  }
}
