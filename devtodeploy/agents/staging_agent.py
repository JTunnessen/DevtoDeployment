from __future__ import annotations

from pathlib import Path

from devtodeploy.agents.base import BaseAgent, PipelineHaltException
from devtodeploy.config import CloudProvider
from devtodeploy.integrations.docker_builder import DockerBuilder
from devtodeploy.integrations.loadtest_runner import LoadTestRunner
from devtodeploy.integrations.terraform_runner import TerraformRunner
from devtodeploy.state import DeploymentInfo, PipelineState
from devtodeploy.utils.terraform_workspace import prepare_terraform_workspace


class StagingAgent(BaseAgent):
    name = "StagingAgent"
    stage_number = 8

    def run(self, state: PipelineState) -> PipelineState:
        state.mark_stage_running(self.stage_number)
        assert state.app_spec is not None
        assert state.development_result is not None

        app_dir = str(Path(self.config.workspace_dir) / state.pipeline_id / "app")
        app_name = state.app_spec.suggested_repo_name.replace("_", "-").lower()

        # Reuse image built in Stage 4; only build here if Stage 4 was skipped/failed
        docker = DockerBuilder()
        image_uri = state.docker_image_uri or self._build_image(docker, app_dir, app_name, "staging")

        tf_work_dir = prepare_terraform_workspace(
            self.config.workspace_dir,
            state.pipeline_id,
            "staging",
            self.config.cloud_provider,
            self.config.deployment_target,
        )
        tf = TerraformRunner(tf_work_dir)

        variables = self._build_tf_variables(state, "staging", image_uri)

        self.logger.info("terraform_init_staging")
        tf.init()

        self.logger.info("terraform_apply_staging", variables=list(variables.keys()))
        tf.apply(variables)

        outputs = tf.output()
        staging_url = outputs.get("app_url", outputs.get("url", ""))
        if not staging_url:
            self.logger.warning("staging_url_not_found_in_outputs", outputs=outputs)
            staging_url = "http://staging-url-not-available"

        self.logger.info("staging_deployed", url=staging_url)

        # Load test
        runner = LoadTestRunner()
        self.logger.info("k6_load_test_starting", url=staging_url, users=self.config.max_load_test_users)
        load_result = runner.run_k6(
            base_url=staging_url,
            max_users=self.config.max_load_test_users,
        )

        state.staging_deployment = DeploymentInfo(
            environment="staging",
            cloud_provider=self.config.cloud_provider.value,
            deployment_target=self.config.deployment_target.value,
            url=staging_url,
            terraform_outputs=outputs,
            load_test=load_result,
        )

        if not load_result.passed:
            msg = (
                f"Load test FAILED: p95={load_result.p95_response_ms:.0f}ms, "
                f"error_rate={load_result.error_rate_percent:.1f}%"
            )
            self.logger.error("load_test_failed", msg=msg)
            state.mark_stage_failed(self.stage_number, msg)
            raise PipelineHaltException(msg)

        state.mark_stage_complete(self.stage_number)
        self.logger.info(
            "staging_complete",
            url=staging_url,
            p95_ms=load_result.p95_response_ms,
            error_rate=load_result.error_rate_percent,
        )
        return state

    def _build_image(
        self, docker: DockerBuilder, app_dir: str, app_name: str, tag: str
    ) -> str:
        try:
            if self.config.cloud_provider == CloudProvider.GCP:
                return docker.build_and_push_gcp(
                    app_dir, self.config.gcp_project_id, app_name, tag
                )
            else:
                registry = getattr(self.config, "azure_container_registry", "")
                return docker.build_and_push_azure(app_dir, registry, app_name, tag)
        except Exception as exc:
            self.logger.warning("docker_build_skipped", reason=str(exc))
            return ""

    def _build_tf_variables(
        self, state: PipelineState, env: str, image_uri: str = ""
    ) -> dict[str, str]:
        assert state.app_spec is not None
        app_name = state.app_spec.suggested_repo_name.replace("_", "-").lower()
        service_name = f"{app_name}-{env}"[:49]
        base: dict[str, str] = {
            "app_name": service_name,
            "environment": env,
        }
        if image_uri:
            base["docker_image"] = image_uri
        if self.config.cloud_provider == CloudProvider.AZURE:
            base.update(
                {
                    "subscription_id": self.config.azure_subscription_id,
                    "resource_group": self.config.azure_resource_group,
                    "location": self.config.azure_region,
                }
            )
        else:
            base.update(
                {
                    "project_id": self.config.gcp_project_id,
                    "region": self.config.gcp_region,
                }
            )
        return base
