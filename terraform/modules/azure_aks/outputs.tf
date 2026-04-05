output "app_url" {
  description = "Placeholder — obtain after deploying K8s Ingress"
  value       = "https://${azurerm_kubernetes_cluster.aks.name}.${var.location}.cloudapp.azure.com"
}

output "cluster_name" {
  value = azurerm_kubernetes_cluster.aks.name
}

output "kube_config" {
  value     = azurerm_kubernetes_cluster.aks.kube_config_raw
  sensitive = true
}
