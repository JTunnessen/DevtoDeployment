from __future__ import annotations

import shutil
from pathlib import Path

import httpx

from devtodeploy.agents.base import BaseAgent, PipelineHaltException
from devtodeploy.config import CloudProvider
from devtodeploy.integrations.github_client import GitHubClient
from devtodeploy.integrations.terraform_runner import TerraformRunner
from devtodeploy.state import DeploymentInfo, PipelineState


class ProductionAgent(BaseAgent):
    name = "ProductionAgent"
    stage_number = 9

    def run(self, state: PipelineState) -> PipelineState:
        state.mark_stage_running(self.stage_number)

        # Gate: staging must have completed and human must have approved
        if not state.staging_deployment:
            msg = "Production deploy blocked: staging deployment not found in state"
            state.mark_stage_failed(self.stage_number, msg)
            raise PipelineHaltException(msg)

        if state.human_approved is not True:
            msg = "Production deploy blocked: human QA approval not recorded"
            state.mark_stage_failed(self.stage_number, msg)
            raise PipelineHaltException(msg)

        jenkins_ok = (
            state.jenkins_result is None  # Jenkins was skipped
            or state.jenkins_result.status == "SUCCESS"
        )
        if not jenkins_ok:
            msg = f"Production deploy blocked: Jenkins status is {state.jenkins_result.status}"  # type: ignore[union-attr]
            state.mark_stage_failed(self.stage_number, msg)
            raise PipelineHaltException(msg)

        tf_work_dir = self._prepare_terraform_workspace(state)
        tf = TerraformRunner(tf_work_dir)
        variables = self._build_tf_variables(state)

        self.logger.info("terraform_init_production")
        tf.init()

        self.logger.info("terraform_apply_production")
        tf.apply(variables)

        outputs = tf.output()
        prod_url = outputs.get("app_url", outputs.get("url", ""))
        if not prod_url:
            self.logger.warning("prod_url_not_found_in_outputs", outputs=outputs)
            prod_url = "http://production-url-not-available"

        self.logger.info("production_deployed", url=prod_url)

        # Smoke test
        smoke_ok = self._smoke_test(prod_url)
        if not smoke_ok:
            msg = f"Production smoke test failed for {prod_url}"
            state.mark_stage_failed(self.stage_number, msg)
            raise PipelineHaltException(msg)

        state.production_deployment = DeploymentInfo(
            environment="production",
            cloud_provider=self.config.cloud_provider.value,
            deployment_target=self.config.deployment_target.value,
            url=prod_url,
            terraform_outputs=outputs,
        )

        # Tag + GitHub Release
        self._create_release(state)

        state.mark_stage_complete(self.stage_number)
        self.logger.info("production_complete", url=prod_url)
        return state

    def _smoke_test(self, url: str, retries: int = 5) -> bool:
        health_url = url.rstrip("/") + "/health"
        for attempt in range(1, retries + 1):
            try:
                resp = httpx.get(health_url, timeout=10)
                if resp.status_code == 200:
                    self.logger.info("smoke_test_passed", url=health_url)
                    return True
                self.logger.warning("smoke_test_non_200", status=resp.status_code, attempt=attempt)
            except Exception as exc:
                self.logger.warning("smoke_test_error", error=str(exc), attempt=attempt)
        return False

    def _create_release(self, state: PipelineState) -> None:
        if not state.github_repo_name:
            return
        try:
            gh = GitHubClient(self.config.github_token, self.config.github_org)
            repo = gh.get_repo_from_url(state.github_repo_url)
            gh.create_tag(repo, "v1.0.0", "Release v1.0.0")
            body = (
                f"## {state.app_spec.app_name} v1.0.0\n\n"  # type: ignore[union-attr]
                f"**Production URL:** {state.production_deployment.url}\n\n"  # type: ignore[union-attr]
                f"### Features\n"
                + "".join(
                    f"- {f}\n" for f in (state.app_spec.features if state.app_spec else [])
                )
                + "\n### Security\nSee [SECURITY.md](SECURITY.md) and "
                "[NIST_800_53.md](NIST_800_53.md) for security documentation.\n"
            )
            gh.create_release(repo, "v1.0.0", f"{state.app_spec.app_name} v1.0.0", body)  # type: ignore[union-attr]
        except Exception as exc:
            self.logger.warning("release_creation_failed", error=str(exc))

    def _prepare_terraform_workspace(self, state: PipelineState) -> str:
        repo_root = Path(__file__).parent.parent.parent
        src = repo_root / "terraform" / "production"
        dest = Path(self.config.workspace_dir) / state.pipeline_id / "terraform" / "production"
        dest.mkdir(parents=True, exist_ok=True)
        for tf_file in src.glob("*.tf"):
            shutil.copy(tf_file, dest / tf_file.name)

        from devtodeploy.agents.staging_agent import _MODULE_MAP
        module_key = (self.config.cloud_provider, self.config.deployment_target)
        module_name = _MODULE_MAP.get(module_key, "azure_appservice")
        module_src = repo_root / "terraform" / "modules" / module_name
        module_dest = dest / "modules" / module_name
        if module_src.exists():
            shutil.copytree(str(module_src), str(module_dest), dirs_exist_ok=True)

        return str(dest)

    def _build_tf_variables(self, state: PipelineState) -> dict[str, str]:
        assert state.app_spec is not None
        app_name = state.app_spec.suggested_repo_name.replace("-", "_")
        base: dict[str, str] = {
            "app_name": f"{app_name}_production",
            "environment": "production",
            "cloud_provider": self.config.cloud_provider.value,
            "min_replicas": "2",
            "max_replicas": "10",
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
