from __future__ import annotations

from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class CloudProvider(str, Enum):
    AZURE = "azure"
    GCP = "gcp"


class DeploymentTarget(str, Enum):
    APP_SERVICE = "app_service"
    AKS = "aks"
    CLOUD_RUN = "cloud_run"
    GKE = "gke"


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Anthropic
    anthropic_api_key: str = Field(..., description="Anthropic API key")
    claude_model: str = Field("claude-sonnet-4-6", description="Claude model ID")

    # GitHub
    github_token: str = Field(..., description="GitHub personal access token")
    github_org: str = Field(..., description="GitHub org or username for created repos")

    # Jenkins
    jenkins_url: str = Field(
        "http://your-jenkins:8080",
        description="Jenkins server URL (placeholder disables the stage)",
    )
    jenkins_user: str = Field("admin", description="Jenkins username")
    jenkins_api_token: str = Field("", description="Jenkins API token")
    jenkins_job_name: str = Field(
        "devtodeploy-functional", description="Jenkins job name to trigger"
    )

    # Cloud
    cloud_provider: CloudProvider = Field(CloudProvider.AZURE)
    deployment_target: DeploymentTarget = Field(DeploymentTarget.APP_SERVICE)

    # Azure
    azure_subscription_id: str = Field("")
    azure_resource_group: str = Field("devtodeploy-rg")
    azure_region: str = Field("eastus")

    # GCP
    gcp_project_id: str = Field("")
    gcp_region: str = Field("us-central1")
    gcp_credentials_file: str = Field("")

    # Pipeline tuning
    max_dev_iterations: int = Field(10, ge=1, le=10)
    max_load_test_users: int = Field(10000, ge=1)
    load_test_tool: str = Field("k6")
    workspace_dir: str = Field("/tmp/devtodeploy")
    halt_on_jenkins_failure: bool = Field(False)

    @property
    def jenkins_is_placeholder(self) -> bool:
        """True when Jenkins hasn't been configured yet."""
        return (
            not self.jenkins_api_token
            or "your-jenkins" in self.jenkins_url
            or not self.jenkins_url
        )
