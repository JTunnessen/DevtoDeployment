variable "app_name"        { type = string }
variable "environment"     { type = string; default = "production" }
variable "cloud_provider"  { type = string; default = "azure" }

# Azure
variable "subscription_id" { type = string; default = "" }
variable "resource_group"  { type = string; default = "devtodeploy-rg" }
variable "location"        { type = string; default = "eastus" }

# GCP
variable "project_id"      { type = string; default = "" }
variable "region"          { type = string; default = "us-central1" }

# Production-scale defaults
variable "min_replicas"    { type = number; default = 2 }
variable "max_replicas"    { type = number; default = 10 }
variable "docker_image"    { type = string; default = "" }
variable "custom_domain"   { type = string; default = "" }
