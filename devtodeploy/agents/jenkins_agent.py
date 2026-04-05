from __future__ import annotations

from devtodeploy.agents.base import BaseAgent, PipelineHaltException
from devtodeploy.integrations.jenkins_client import JenkinsClient
from devtodeploy.state import JenkinsResult, PipelineState


class JenkinsAgent(BaseAgent):
    name = "JenkinsAgent"
    stage_number = 6

    def run(self, state: PipelineState) -> PipelineState:
        state.mark_stage_running(self.stage_number)

        if self.config.jenkins_is_placeholder:
            self.logger.warning(
                "jenkins_skipped",
                reason="Jenkins not configured (placeholder URL or missing token). "
                       "See docs/jenkins_setup.md to configure Jenkins.",
            )
            state.mark_stage_skipped(
                self.stage_number,
                "Jenkins not configured — see docs/jenkins_setup.md",
            )
            return state

        client = JenkinsClient(
            url=self.config.jenkins_url,
            user=self.config.jenkins_user,
            token=self.config.jenkins_api_token,
        )

        if not client.test_connection():
            msg = f"Cannot connect to Jenkins at {self.config.jenkins_url}"
            self.logger.error("jenkins_unreachable", url=self.config.jenkins_url)
            if self.config.halt_on_jenkins_failure:
                state.mark_stage_failed(self.stage_number, msg)
                raise PipelineHaltException(msg)
            state.mark_stage_skipped(self.stage_number, msg)
            return state

        self.logger.info("triggering_jenkins_build", job=self.config.jenkins_job_name)
        build_number = client.trigger_build(
            self.config.jenkins_job_name,
            parameters={
                "GIT_REPO": state.github_repo_url,
                "BRANCH": "main",
            },
        )

        build_info = client.wait_for_build(self.config.jenkins_job_name, build_number)
        test_report = client.get_test_report(self.config.jenkins_job_name, build_number)

        result = JenkinsResult(
            build_number=build_number,
            build_url=build_info.get("url", ""),
            status=build_info.get("result", "UNKNOWN"),
            test_total=test_report.get("totalCount", 0),
            test_passed=test_report.get("passCount", 0),
            test_failed=test_report.get("failCount", 0),
            duration_seconds=build_info.get("duration", 0) / 1000,
        )
        state.jenkins_result = result

        self.logger.info(
            "jenkins_complete",
            status=result.status,
            passed=result.test_passed,
            failed=result.test_failed,
        )

        if result.status != "SUCCESS" and self.config.halt_on_jenkins_failure:
            msg = f"Jenkins build #{build_number} returned {result.status}"
            state.mark_stage_failed(self.stage_number, msg)
            raise PipelineHaltException(msg)

        state.mark_stage_complete(self.stage_number)
        return state
