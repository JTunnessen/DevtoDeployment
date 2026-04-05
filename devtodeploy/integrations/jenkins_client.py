from __future__ import annotations

import time
from typing import Any

import jenkins

from devtodeploy.utils.logging import get_logger
from devtodeploy.utils.retry import with_retry

logger = get_logger("jenkins_client")


class JenkinsClient:
    def __init__(self, url: str, user: str, token: str) -> None:
        self.server = jenkins.Jenkins(url, username=user, password=token)
        self._job_cache: dict[str, Any] = {}

    def test_connection(self) -> bool:
        """Return True if the Jenkins server is reachable."""
        try:
            self.server.get_whoami()
            return True
        except Exception:
            return False

    @with_retry(max_attempts=3, min_wait=2, max_wait=8)
    def trigger_build(self, job_name: str, parameters: dict[str, str]) -> int:
        """Trigger a job and return the resulting build number."""
        queue_id = self.server.build_job(job_name, parameters=parameters)
        logger.info("jenkins_build_queued", job=job_name, queue_id=queue_id)

        # Poll queue until the build number is assigned (up to 60s)
        deadline = time.time() + 60
        while time.time() < deadline:
            time.sleep(5)
            try:
                queue_item = self.server.get_queue_item(queue_id)
                if "executable" in queue_item:
                    build_number = queue_item["executable"]["number"]
                    logger.info("jenkins_build_started", job=job_name, build=build_number)
                    return build_number
            except Exception:
                pass

        raise TimeoutError(f"Jenkins build for {job_name} did not start within 60s")

    @with_retry(max_attempts=4, min_wait=2, max_wait=16)
    def wait_for_build(
        self,
        job_name: str,
        build_number: int,
        timeout_seconds: int = 3600,
        poll_interval: int = 30,
    ) -> dict[str, Any]:
        """Poll until a build completes. Returns the build_info dict."""
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            info = self.server.get_build_info(job_name, build_number)
            if not info.get("building", True):
                logger.info(
                    "jenkins_build_complete",
                    job=job_name,
                    build=build_number,
                    result=info.get("result"),
                )
                return info
            logger.info(
                "jenkins_build_running",
                job=job_name,
                build=build_number,
                elapsed=int(info.get("duration", 0) / 1000),
            )
            time.sleep(poll_interval)

        raise TimeoutError(
            f"Jenkins build {job_name}#{build_number} did not finish within {timeout_seconds}s"
        )

    def get_test_report(self, job_name: str, build_number: int) -> dict[str, Any]:
        """Fetch the JUnit test report for a completed build. Returns {} on failure."""
        try:
            return self.server.get_build_test_report(job_name, build_number)
        except Exception as exc:
            logger.warning("jenkins_test_report_unavailable", reason=str(exc))
            return {}
