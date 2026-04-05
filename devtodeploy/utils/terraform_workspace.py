"""Utilities for preparing per-pipeline Terraform workspaces."""
from __future__ import annotations

import shutil
from pathlib import Path

from devtodeploy.config import CloudProvider, DeploymentTarget

# Maps (cloud, target) → module directory name
_MODULE_MAP: dict[tuple[CloudProvider, DeploymentTarget], str] = {
    (CloudProvider.AZURE, DeploymentTarget.APP_SERVICE): "azure_appservice",
    (CloudProvider.AZURE, DeploymentTarget.AKS): "azure_aks",
    (CloudProvider.GCP, DeploymentTarget.CLOUD_RUN): "gcp_cloudrun",
    (CloudProvider.GCP, DeploymentTarget.GKE): "gcp_gke",
}

# ---------------------------------------------------------------------------
# Cloud-specific root main.tf templates (provider in root, not in module)
# ---------------------------------------------------------------------------

_GCP_CLOUDRUN_MAIN = """\
terraform {{
  required_version = ">= 1.7"
  required_providers {{
    google = {{
      source  = "hashicorp/google"
      version = "~> 5.0"
    }}
  }}
}}

provider "google" {{
  project = var.project_id
  region  = var.region
}}

module "gcp_cloudrun" {{
  source = "./modules/gcp_cloudrun"

  app_name     = var.app_name
  environment  = var.environment
  project_id   = var.project_id
  region       = var.region
  min_replicas = var.min_replicas
  max_replicas = var.max_replicas
  docker_image = var.docker_image != "" ? var.docker_image : "gcr.io/cloudrun/hello"
}}

output "app_url" {{
  value = module.gcp_cloudrun.app_url
}}
"""

_GCP_GKE_MAIN = """\
terraform {{
  required_version = ">= 1.7"
  required_providers {{
    google = {{
      source  = "hashicorp/google"
      version = "~> 5.0"
    }}
  }}
}}

provider "google" {{
  project = var.project_id
  region  = var.region
}}

module "gcp_gke" {{
  source = "./modules/gcp_gke"

  app_name     = var.app_name
  environment  = var.environment
  project_id   = var.project_id
  region       = var.region
  min_replicas = var.min_replicas
  max_replicas = var.max_replicas
  docker_image = var.docker_image
}}

output "app_url" {{
  value = module.gcp_gke.app_url
}}
"""

_AZURE_APPSERVICE_MAIN = """\
terraform {{
  required_version = ">= 1.7"
  required_providers {{
    azurerm = {{
      source  = "hashicorp/azurerm"
      version = "~> 3.90"
    }}
  }}
}}

provider "azurerm" {{
  features {{}}
  subscription_id = var.subscription_id
}}

module "azure_appservice" {{
  source = "./modules/azure_appservice"

  app_name        = var.app_name
  environment     = var.environment
  subscription_id = var.subscription_id
  resource_group  = var.resource_group
  location        = var.location
  sku_name        = "B1"
  min_replicas    = var.min_replicas
  max_replicas    = var.max_replicas
  docker_image    = var.docker_image
}}

output "app_url" {{
  value = module.azure_appservice.app_url
}}
"""

_AZURE_AKS_MAIN = """\
terraform {{
  required_version = ">= 1.7"
  required_providers {{
    azurerm = {{
      source  = "hashicorp/azurerm"
      version = "~> 3.90"
    }}
  }}
}}

provider "azurerm" {{
  features {{}}
  subscription_id = var.subscription_id
}}

module "azure_aks" {{
  source = "./modules/azure_aks"

  app_name        = var.app_name
  environment     = var.environment
  subscription_id = var.subscription_id
  resource_group  = var.resource_group
  location        = var.location
  min_replicas    = var.min_replicas
  max_replicas    = var.max_replicas
  docker_image    = var.docker_image
}}

output "app_url" {{
  value = module.azure_aks.app_url
}}
"""

_GCP_VARIABLES = """\
variable "app_name"     { type = string }
variable "environment"  { type = string  default = "staging" }
variable "project_id"   { type = string  default = "" }
variable "region"       { type = string  default = "us-central1" }
variable "min_replicas" { type = number  default = 1 }
variable "max_replicas" { type = number  default = 3 }
variable "docker_image" { type = string  default = "" }
"""

_AZURE_VARIABLES = """\
variable "app_name"        { type = string }
variable "environment"     { type = string  default = "staging" }
variable "subscription_id" { type = string  default = "" }
variable "resource_group"  { type = string  default = "devtodeploy-rg" }
variable "location"        { type = string  default = "eastus" }
variable "min_replicas"    { type = number  default = 1 }
variable "max_replicas"    { type = number  default = 3 }
variable "docker_image"    { type = string  default = "" }
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
    Build a self-contained Terraform workspace directory for the given environment.

    Generates a cloud-specific main.tf (with the provider block in the root,
    not in the module) and copies only the relevant module directory.
    Returns the path to the workspace directory.
    """
    repo_root = Path(__file__).parent.parent.parent
    dest = Path(workspace_dir) / pipeline_id / "terraform" / env
    dest.mkdir(parents=True, exist_ok=True)

    # Write cloud-specific main.tf
    key = (cloud_provider, deployment_target)
    main_tf = _MAIN_TF_MAP.get(key, _GCP_CLOUDRUN_MAIN)
    (dest / "main.tf").write_text(main_tf, encoding="utf-8")

    # Write variables.tf
    variables_tf = (
        _GCP_VARIABLES
        if cloud_provider == CloudProvider.GCP
        else _AZURE_VARIABLES
    )
    (dest / "variables.tf").write_text(variables_tf, encoding="utf-8")

    # Copy the selected module
    module_name = _MODULE_MAP.get(key)
    if module_name:
        module_src = repo_root / "terraform" / "modules" / module_name
        module_dest = dest / "modules" / module_name
        if module_src.exists():
            if module_dest.exists():
                shutil.rmtree(str(module_dest))
            shutil.copytree(str(module_src), str(module_dest))

    return str(dest)
