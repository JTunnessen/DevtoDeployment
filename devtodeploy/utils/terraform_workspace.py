"""Utilities for preparing per-pipeline Terraform workspaces."""
from __future__ import annotations

import shutil
from pathlib import Path

from devtodeploy.config import CloudProvider, DeploymentTarget

# Maps (cloud, target) -> module directory name
_MODULE_MAP: dict[tuple[CloudProvider, DeploymentTarget], str] = {
    (CloudProvider.AZURE, DeploymentTarget.APP_SERVICE): "azure_appservice",
    (CloudProvider.AZURE, DeploymentTarget.AKS): "azure_aks",
    (CloudProvider.GCP, DeploymentTarget.CLOUD_RUN): "gcp_cloudrun",
    (CloudProvider.GCP, DeploymentTarget.GKE): "gcp_gke",
}

# ---------------------------------------------------------------------------
# Cloud-specific root main.tf templates
# Provider block lives here (root), NOT inside modules.
# ---------------------------------------------------------------------------

_GCP_CLOUDRUN_MAIN = (
    'terraform {\n'
    '  required_version = ">= 1.7"\n'
    '  required_providers {\n'
    '    google = {\n'
    '      source  = "hashicorp/google"\n'
    '      version = "~> 5.0"\n'
    '    }\n'
    '  }\n'
    '}\n'
    '\n'
    'provider "google" {\n'
    '  project = var.project_id\n'
    '  region  = var.region\n'
    '}\n'
    '\n'
    'module "gcp_cloudrun" {\n'
    '  source = "./modules/gcp_cloudrun"\n'
    '\n'
    '  app_name     = var.app_name\n'
    '  environment  = var.environment\n'
    '  project_id   = var.project_id\n'
    '  region       = var.region\n'
    '  min_replicas = var.min_replicas\n'
    '  max_replicas = var.max_replicas\n'
    '  docker_image = var.docker_image != "" ? var.docker_image : "gcr.io/cloudrun/hello"\n'
    '}\n'
    '\n'
    'output "app_url" {\n'
    '  value = module.gcp_cloudrun.app_url\n'
    '}\n'
)

_GCP_GKE_MAIN = (
    'terraform {\n'
    '  required_version = ">= 1.7"\n'
    '  required_providers {\n'
    '    google = {\n'
    '      source  = "hashicorp/google"\n'
    '      version = "~> 5.0"\n'
    '    }\n'
    '  }\n'
    '}\n'
    '\n'
    'provider "google" {\n'
    '  project = var.project_id\n'
    '  region  = var.region\n'
    '}\n'
    '\n'
    'module "gcp_gke" {\n'
    '  source = "./modules/gcp_gke"\n'
    '\n'
    '  app_name     = var.app_name\n'
    '  environment  = var.environment\n'
    '  project_id   = var.project_id\n'
    '  region       = var.region\n'
    '  min_replicas = var.min_replicas\n'
    '  max_replicas = var.max_replicas\n'
    '  docker_image = var.docker_image\n'
    '}\n'
    '\n'
    'output "app_url" {\n'
    '  value = module.gcp_gke.app_url\n'
    '}\n'
)

_AZURE_APPSERVICE_MAIN = (
    'terraform {\n'
    '  required_version = ">= 1.7"\n'
    '  required_providers {\n'
    '    azurerm = {\n'
    '      source  = "hashicorp/azurerm"\n'
    '      version = "~> 3.90"\n'
    '    }\n'
    '  }\n'
    '}\n'
    '\n'
    'provider "azurerm" {\n'
    '  features {}\n'
    '  subscription_id = var.subscription_id\n'
    '}\n'
    '\n'
    'module "azure_appservice" {\n'
    '  source = "./modules/azure_appservice"\n'
    '\n'
    '  app_name        = var.app_name\n'
    '  environment     = var.environment\n'
    '  subscription_id = var.subscription_id\n'
    '  resource_group  = var.resource_group\n'
    '  location        = var.location\n'
    '  sku_name        = "B1"\n'
    '  min_replicas    = var.min_replicas\n'
    '  max_replicas    = var.max_replicas\n'
    '  docker_image    = var.docker_image\n'
    '}\n'
    '\n'
    'output "app_url" {\n'
    '  value = module.azure_appservice.app_url\n'
    '}\n'
)

_AZURE_AKS_MAIN = (
    'terraform {\n'
    '  required_version = ">= 1.7"\n'
    '  required_providers {\n'
    '    azurerm = {\n'
    '      source  = "hashicorp/azurerm"\n'
    '      version = "~> 3.90"\n'
    '    }\n'
    '  }\n'
    '}\n'
    '\n'
    'provider "azurerm" {\n'
    '  features {}\n'
    '  subscription_id = var.subscription_id\n'
    '}\n'
    '\n'
    'module "azure_aks" {\n'
    '  source = "./modules/azure_aks"\n'
    '\n'
    '  app_name        = var.app_name\n'
    '  environment     = var.environment\n'
    '  subscription_id = var.subscription_id\n'
    '  resource_group  = var.resource_group\n'
    '  location        = var.location\n'
    '  min_replicas    = var.min_replicas\n'
    '  max_replicas    = var.max_replicas\n'
    '  docker_image    = var.docker_image\n'
    '}\n'
    '\n'
    'output "app_url" {\n'
    '  value = module.azure_aks.app_url\n'
    '}\n'
)

_GCP_VARIABLES = """\
variable "app_name" {
  type = string
}
variable "environment" {
  type    = string
  default = "staging"
}
variable "project_id" {
  type    = string
  default = ""
}
variable "region" {
  type    = string
  default = "us-central1"
}
variable "min_replicas" {
  type    = number
  default = 1
}
variable "max_replicas" {
  type    = number
  default = 3
}
variable "docker_image" {
  type    = string
  default = ""
}
"""

_AZURE_VARIABLES = """\
variable "app_name" {
  type = string
}
variable "environment" {
  type    = string
  default = "staging"
}
variable "subscription_id" {
  type    = string
  default = ""
}
variable "resource_group" {
  type    = string
  default = "devtodeploy-rg"
}
variable "location" {
  type    = string
  default = "eastus"
}
variable "min_replicas" {
  type    = number
  default = 1
}
variable "max_replicas" {
  type    = number
  default = 3
}
variable "docker_image" {
  type    = string
  default = ""
}
"""

_MAIN_TF_MAP: dict[tuple[CloudProvider, DeploymentTarget], str] = {
    (CloudProvider.GCP, DeploymentTarget.CLOUD_RUN): _GCP_CLOUDRUN_MAIN,
    (CloudProvider.GCP, DeploymentTarget.GKE): _GCP_GKE_MAIN,
    (CloudProvider.AZURE, DeploymentTarget.APP_SERVICE): _AZURE_APPSERVICE_MAIN,
    (CloudProvider.AZURE, DeploymentTarget.AKS): _AZURE_AKS_MAIN,
}


def prepare_terraform_workspace(
    workspace_dir: str,
    pipeline_id: str,
    env: str,
    cloud_provider: CloudProvider,
    deployment_target: DeploymentTarget,
) -> str:
    """
    Build a self-contained Terraform workspace for the given environment.

    Generates a cloud-specific main.tf (provider in root, not in module)
    and copies only the relevant module. Returns the workspace path.
    """
    repo_root = Path(__file__).parent.parent.parent
    dest = Path(workspace_dir) / pipeline_id / "terraform" / env
    dest.mkdir(parents=True, exist_ok=True)

    key = (cloud_provider, deployment_target)

    # Write cloud-specific main.tf
    main_tf = _MAIN_TF_MAP.get(key, _GCP_CLOUDRUN_MAIN)
    (dest / "main.tf").write_text(main_tf, encoding="utf-8")

    # Write variables.tf
    variables_tf = (
        _GCP_VARIABLES if cloud_provider == CloudProvider.GCP else _AZURE_VARIABLES
    )
    (dest / "variables.tf").write_text(variables_tf, encoding="utf-8")

    # Copy only the relevant module
    module_name = _MODULE_MAP.get(key)
    if module_name:
        module_src = repo_root / "terraform" / "modules" / module_name
        module_dest = dest / "modules" / module_name
        if module_src.exists():
            if module_dest.exists():
                shutil.rmtree(str(module_dest))
            shutil.copytree(str(module_src), str(module_dest))

    return str(dest)
