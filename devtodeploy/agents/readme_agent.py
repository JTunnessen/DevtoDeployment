from __future__ import annotations

from devtodeploy.agents.base import BaseAgent
from devtodeploy.integrations.github_client import GitHubClient
from devtodeploy.prompts import readme as prompts
from devtodeploy.state import PipelineState


class ReadmeAgent(BaseAgent):
    name = "ReadmeAgent"
    stage_number = 5

    def run(self, state: PipelineState) -> PipelineState:
        state.mark_stage_running(self.stage_number)
        assert state.development_result is not None
        assert state.app_spec is not None

        spec_json = state.app_spec.model_dump_json(indent=2)
        source_summary = "\n".join(
            f"- {path}" for path in sorted(state.development_result.final_files)
        )
        scan_summary = self._build_scan_summary(state)

        readme = self._call_claude(
            prompts.SYSTEM,
            [{"role": "user", "content": prompts.user_prompt(spec_json, source_summary, scan_summary)}],
            max_tokens=4096,
        )

        state.readme_content = readme

        # Push to GitHub
        gh = GitHubClient(self.config.github_token, self.config.github_org)
        repo = gh.get_repo_from_url(state.github_repo_url)
        gh.create_or_update_file(
            repo,
            "README.md",
            readme,
            "docs: add README.md",
        )

        state.mark_stage_complete(self.stage_number)
        self.logger.info("readme_pushed", repo=state.github_repo_name)
        return state

    def _build_scan_summary(self, state: PipelineState) -> str:
        if not state.scan_result:
            return "No scan results available."
        sr = state.scan_result
        return (
            f"Bandit + Safety scan: HIGH={sr.high_count}, MEDIUM={sr.medium_count}, "
            f"LOW={sr.low_count}. Passed: {sr.passed}."
        )
