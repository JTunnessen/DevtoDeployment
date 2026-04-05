output "app_url" {
  description = "Placeholder — obtain after deploying K8s LoadBalancer Ingress"
  value       = "https://${google_container_cluster.gke.name}.${var.region}.cluster"
}

output "cluster_name" {
  value = google_container_cluster.gke.name
}

output "endpoint" {
  value     = google_container_cluster.gke.endpoint
  sensitive = true
}
