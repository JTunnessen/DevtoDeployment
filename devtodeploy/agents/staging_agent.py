from __future__ import annotations

import shutil
from pathlib import Path

from devtodeploy.agents.base import BaseAgent, PipelineHaltException
from devtodeploy.config import CloudProvider, DeploymentTarget
from devtodeploy.integrations.loadtest_runner import LoadTestRunner
from devtodeploy.integrations.terraform_runner import TerraformRunner
from devtodeploy.state import DeploymentInfo, PipelineState

_MODULE_MAP: dict[tuple[CloudProvider, DeploymentTarget], str] = {
    (CloudProvider.AZURE, DeploymentTarget.APP_SERVICE): "azure_appservice",
    (CloudProvider.AZURE, DeploymentTarget.AKS): "azure_aks",
    (CloudProvider.GCP, DeploymentTarget.CLOUD_RUN): "gcp_cloudrun",
    (CloudProvider.GCP, DeploymentTarget.GKE): "gcp_gke",
}


class StagingAgent(BaseAgent):
    name = "StagingAgent"
    stage_number = 8

    def run(self, state: PipelineState) -> PipelineState:
        state.mark_stage_running(self.stage_number)
        assert state.app_spec is not None
        assert state.development_result is not None

        tf_work_dir = self._prepare_terraform_workspace(state, "staging")
        tf = TerraformRunner(tf_work_dir)

        variables = self._build_tf_variables(state, "staging")

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

    def _prepare_terraform_workspace(self, state: PipelineState, env: str) -> str:
        """Copy the staging/production Terraform configs into the pipeline workspace."""
        repo_root = Path(__file__).parent.parent.parent
        src = repo_root / "terraform" / env
        dest = Path(self.config.workspace_dir) / state.pipeline_id / "terraform" / env
        dest.mkdir(parents=True, exist_ok=True)

        # Copy main terraform config
        for tf_file in src.glob("*.tf"):
            shutil.copy(tf_file, dest / tf_file.name)

        # Copy the selected module
        module_key = (self.config.cloud_provider, self.config.deployment_target)
        module_name = _MODULE_MAP.get(module_key, "azure_appservice")
        module_src = repo_root / "terraform" / "modules" / module_name
        module_dest = dest / "modules" / module_name
        if module_src.exists():
            shutil.copytree(str(module_src), str(module_dest), dirs_exist_ok=True)

        return str(dest)

    def _build_tf_variables(self, state: PipelineState, env: str) -> dict[str, str]:
        assert state.app_spec is not None
        app_name = state.app_spec.suggested_repo_name.replace("-", "_")
        base: dict[str, str] = {
            "app_name": f"{app_name}_{env}",
            "environment": env,
            "cloud_provider": self.config.cloud_provider.value,
        }
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
