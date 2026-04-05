terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.90"
    }
  }
}

resource "azurerm_service_plan" "plan" {
  name                = "${var.app_name}-plan"
  resource_group_name = var.resource_group
  location            = var.location
  os_type             = "Linux"
  sku_name            = var.sku_name
}

resource "azurerm_linux_web_app" "app" {
  name                = var.app_name
  resource_group_name = var.resource_group
  location            = var.location
  service_plan_id     = azurerm_service_plan.plan.id

  site_config {
    always_on        = true
    http2_enabled    = true
    minimum_tls_version = "1.2"

    application_stack {
      docker_image_name   = var.docker_image != "" ? var.docker_image : "nginx:alpine"
      docker_registry_url = "https://index.docker.io"
    }
  }

  app_settings = {
    WEBSITES_PORT           = "8000"
    WEBSITES_ENABLE_APP_SERVICE_STORAGE = "false"
    ENVIRONMENT             = var.environment
  }

  https_only = true

  tags = {
    environment = var.environment
    managed_by  = "devtodeploy"
  }
}

# Auto-scaling (production)
resource "azurerm_monitor_autoscale_setting" "scale" {
  count               = var.max_replicas > 1 ? 1 : 0
  name                = "${var.app_name}-autoscale"
  resource_group_name = var.resource_group
  location            = var.location
  target_resource_id  = azurerm_service_plan.plan.id

  profile {
    name = "default"
    capacity {
      default = var.min_replicas
      minimum = var.min_replicas
      maximum = var.max_replicas
    }
    rule {
      metric_trigger {
        metric_name        = "CpuPercentage"
        metric_resource_id = azurerm_service_plan.plan.id
        time_grain         = "PT1M"
        statistic          = "Average"
        time_window        = "PT5M"
        time_aggregation   = "Average"
        operator           = "GreaterThan"
        threshold          = 70
      }
      scale_action {
        direction = "Increase"
        type      = "ChangeCount"
        value     = "1"
        cooldown  = "PT5M"
      }
    }
  }
}
