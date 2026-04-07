"""Docker image build and push utilities."""
from __future__ import annotations

import platform
import subprocess
from pathlib import Path

from devtodeploy.utils.logging import get_logger

logger = get_logger("docker_builder")

# On Windows, gcloud/docker are .cmd wrappers that need shell=True
_SHELL = platform.system() == "Windows"


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
        # On Windows gcloud/docker are .cmd files; shell=True lets the OS resolve them
        cmd_str = " ".join(cmd)
        logger.info(event, cmd=cmd_str, **log_kwargs)
        result = subprocess.run(
            cmd_str if _SHELL else cmd,
            capture_output=False,
            text=True,
            shell=_SHELL,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"command failed (exit {result.returncode}): {cmd_str}"
            )
