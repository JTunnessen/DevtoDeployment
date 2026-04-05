terraform {
  required_version = ">= 1.7"
}

# ---------------------------------------------------------------------------
# Azure App Service — production (P2v3 SKU, auto-scaling)
# ---------------------------------------------------------------------------
module "azure_appservice" {
  count  = var.cloud_provider == "azure" ? 1 : 0
  source = "./modules/azure_appservice"

  app_name        = var.app_name
  environment     = var.environment
  subscription_id = var.subscription_id
  resource_group  = var.resource_group
  location        = var.location
  sku_name        = "P2v3"
  min_replicas    = var.min_replicas
  max_replicas    = var.max_replicas
  docker_image    = var.docker_image
}

# ---------------------------------------------------------------------------
# GCP Cloud Run — production
# ---------------------------------------------------------------------------
module "gcp_cloudrun" {
  count  = var.cloud_provider == "gcp" ? 1 : 0
  source = "./modules/gcp_cloudrun"

  app_name     = var.app_name
  environment  = var.environment
  project_id   = var.project_id
  region       = var.region
  min_replicas = var.min_replicas
  max_replicas = var.max_replicas
  docker_image = var.docker_image != "" ? var.docker_image : "gcr.io/cloudrun/hello"
  cpu          = "2"
  memory       = "1Gi"
}

output "app_url" {
  value = (
    var.cloud_provider == "azure"
    ? (length(module.azure_appservice) > 0 ? module.azure_appservice[0].app_url : "")
    : (length(module.gcp_cloudrun) > 0 ? module.gcp_cloudrun[0].app_url : "")
  )
}
