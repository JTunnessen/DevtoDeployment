terraform {
  required_providers {
    azurerm = { source = "hashicorp/azurerm"; version = "~> 3.90" }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

resource "azurerm_kubernetes_cluster" "aks" {
  name                = "${var.app_name}-aks"
  location            = var.location
  resource_group_name = var.resource_group
  dns_prefix          = var.app_name

  default_node_pool {
    name       = "default"
    node_count = var.node_count
    vm_size    = var.node_vm_size
    enable_auto_scaling = true
    min_count   = var.min_replicas
    max_count   = var.max_replicas
  }

  identity {
    type = "SystemAssigned"
  }

  network_profile {
    network_plugin    = "azure"
    load_balancer_sku = "standard"
  }

  tags = {
    environment = var.environment
    managed_by  = "devtodeploy"
  }
}
