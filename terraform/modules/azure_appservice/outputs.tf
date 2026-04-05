output "app_url" {
  description = "HTTPS URL of the deployed application"
  value       = "https://${azurerm_linux_web_app.app.default_hostname}"
}

output "app_name" {
  description = "Azure Web App name"
  value       = azurerm_linux_web_app.app.name
}

output "resource_group" {
  description = "Resource group containing the application"
  value       = var.resource_group
}
