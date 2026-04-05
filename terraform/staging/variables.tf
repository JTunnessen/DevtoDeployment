variable "app_name"        { type = string }
variable "environment"     { type = string; default = "staging" }
variable "cloud_provider"  { type = string; default = "azure" }

# Azure
variable "subscription_id" { type = string; default = "" }
variable "resource_group"  { type = string; default = "devtodeploy-rg" }
variable "location"        { type = string; default = "eastus" }

# GCP
variable "project_id"      { type = string; default = "" }
variable "region"          { type = string; default = "us-central1" }

variable "min_replicas"    { type = number; default = 1 }
variable "max_replicas"    { type = number; default = 3 }
variable "docker_image"    { type = string; default = "" }
