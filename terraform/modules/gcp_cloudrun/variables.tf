variable "app_name"     { type = string }
variable "environment"  { type = string; default = "staging" }
variable "project_id"   { type = string }
variable "region"       { type = string; default = "us-central1" }
variable "docker_image" { type = string; default = "gcr.io/cloudrun/hello" }
variable "min_replicas" { type = number; default = 0 }
variable "max_replicas" { type = number; default = 10 }
variable "cpu"          { type = string; default = "1" }
variable "memory"       { type = string; default = "512Mi" }
