"""Docker image build and push utilities."""
from __future__ import annotations

import subprocess
from pathlib import Path

from devtodeploy.utils.logging import get_logger

logger = get_logger("docker_builder")


class DockerBuilder:
    """Builds and pushes a Docker image to GCR or ACR."""

    def build_and_push_gcp(
        self,
        app_dir: str,
        project_id: str,
        app_name: str,
        tag: str = "latest",
    ) -> str:
        """
        Build the app's Docker image and push to Google Container Registry.

        Returns the full image URI: gcr.io/<project_id>/<app_name>:<tag>
        Raises RuntimeError if docker is not available or the build fails.
        """
        image_uri = f"gcr.io/{project_id}/{app_name}:{tag}"
        app_path = Path(app_dir)

        if not (app_path / "Dockerfile").exists():
            raise FileNotFoundError(f"No Dockerfile found in {app_dir}")

        # Configure Docker to authenticate with GCR via gcloud credentials
        self._run(
            ["gcloud", "auth", "configure-docker", "gcr.io", "--quiet"],
            "gcloud_configure_docker",
        )

        # Build
        self._run(
            ["docker", "build", "-t", image_uri, str(app_path)],
            "docker_build",
            image=image_uri,
        )

        # Push
        self._run(
            ["docker", "push", image_uri],
            "docker_push",
            image=image_uri,
        )

        logger.info("image_pushed", uri=image_uri)
        return image_uri

    def build_and_push_azure(
        self,
        app_dir: str,
        registry: str,
        app_name: str,
        tag: str = "latest",
    ) -> str:
        """
        Build and push to Azure Container Registry.

        Returns the full image URI: <registry>/<app_name>:<tag>
        """
        image_uri = f"{registry}/{app_name}:{tag}"
        app_path = Path(app_dir)

        if not (app_path / "Dockerfile").exists():
            raise FileNotFoundError(f"No Dockerfile found in {app_dir}")

        self._run(
            ["docker", "build", "-t", image_uri, str(app_path)],
            "docker_build",
            image=image_uri,
        )
        self._run(
            ["docker", "push", image_uri],
            "docker_push",
            image=image_uri,
        )

        logger.info("image_pushed", uri=image_uri)
        return image_uri

    def _run(self, cmd: list[str], event: str, **log_kwargs) -> None:
        logger.info(event, cmd=" ".join(cmd), **log_kwargs)
        result = subprocess.run(cmd, capture_output=False, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"{cmd[0]} command failed (exit {result.returncode}): {' '.join(cmd)}"
            )
