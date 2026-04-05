variable "app_name"       { type = string }
variable "environment"    { type = string; default = "staging" }
variable "subscription_id" { type = string }
variable "resource_group" { type = string }
variable "location"       { type = string; default = "eastus" }
variable "node_count"     { type = number; default = 2 }
variable "node_vm_size"   { type = string; default = "Standard_D2_v2" }
variable "min_replicas"   { type = number; default = 1 }
variable "max_replicas"   { type = number; default = 5 }
variable "docker_image"   { type = string; default = "" }
