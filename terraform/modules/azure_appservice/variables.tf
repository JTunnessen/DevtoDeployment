variable "app_name" {
  description = "Application name (used for resource naming)"
  type        = string
}

variable "environment" {
  description = "Deployment environment (staging or production)"
  type        = string
  default     = "staging"
}

variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
}

variable "resource_group" {
  description = "Azure Resource Group name"
  type        = string
}

variable "location" {
  description = "Azure region"
  type        = string
  default     = "eastus"
}

variable "sku_name" {
  description = "App Service Plan SKU (B1 for staging, P2v3 for production)"
  type        = string
  default     = "B1"
}

variable "docker_image" {
  description = "Docker image to deploy (optional)"
  type        = string
  default     = ""
}

variable "min_replicas" {
  description = "Minimum number of app instances"
  type        = number
  default     = 1
}

variable "max_replicas" {
  description = "Maximum number of app instances"
  type        = number
  default     = 3
}
