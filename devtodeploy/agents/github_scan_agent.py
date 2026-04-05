from __future__ import annotations

import json
from pathlib import Path

from devtodeploy.agents.base import BaseAgent, PipelineHaltException
from devtodeploy.integrations.github_client import GitHubClient
from devtodeploy.integrations.semgrep_runner import SemgrepRunner
from devtodeploy.state import PipelineState
from devtodeploy.utils.workspace import write_app_files


class GitHubScanAgent(BaseAgent):
    name = "GitHubScanAgent"
    stage_number = 4

    def run(self, state: PipelineState) -> PipelineState:
        state.mark_stage_running(self.stage_number)
        assert state.development_result is not None
        assert state.app_spec is not None

        gh = GitHubClient(self.config.github_token, self.config.github_org)
        scanner = SemgrepRunner()
        app_dir = Path(self.config.workspace_dir) / state.pipeline_id / "app"

        # Create GitHub repo
        repo = gh.create_repo(
            name=state.app_spec.suggested_repo_name,
            description=state.app_spec.raw_description[:255],
            private=False,
        )
        state.github_repo_name = repo.name
        state.github_repo_url = repo.html_url

        # Push code
        gh.push_directory(repo, str(app_dir), commit_msg="feat: initial generated application")
        self.logger.info("code_pushed", url=state.github_repo_url)

        # Semgrep scan + auto-remediation loop (up to 3 cycles)
        for cycle in range(1, 4):
            scan = scanner.run(str(app_dir))
            scan.remediation_cycles = cycle - 1

            if scan.passed:
                state.scan_result = scan
                break

            self.logger.warning(
                "scan_high_findings",
                cycle=cycle,
                high=scan.high_count,
            )
            if cycle == 3:
                # Final cycle — record result and continue (don't halt for scan alone)
                state.scan_result = scan
                self.logger.warning(
                    "scan_still_failing_after_remediation",
                    high=scan.high_count,
                )
                break

            # Ask Claude to fix the HIGH findings
            findings_json = json.dumps(
                [f.model_dump() for f in scan.findings if f.severity == "HIGH"],
                indent=2,
            )
            source_json = json.dumps(state.development_result.final_files, indent=2)
            fix_prompt = (
                "The following HIGH-severity Semgrep findings were found in this code.\n\n"
                f"Findings:\n{findings_json}\n\n"
                f"Source files:\n{source_json}\n\n"
                "Return a corrected JSON file map with ALL HIGH findings fixed. "
                "Return ONLY the JSON object."
            )
            from devtodeploy.prompts.development import SYSTEM as DEV_SYSTEM
            text = self._call_claude(
                DEV_SYSTEM,
                [{"role": "user", "content": fix_prompt}],
                max_tokens=16384,
            )
            # Parse fixed files
            text = text.strip()
            if text.startswith("```"):
                lines = text.splitlines()
                text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
            try:
                fixed_files = json.loads(text)
                state.development_result.final_files = fixed_files
                write_app_files(self.config.workspace_dir, state.pipeline_id, fixed_files)
                gh.push_directory(
                    repo,
                    str(app_dir),
                    commit_msg=f"fix: security remediation cycle {cycle}",
                )
            except json.JSONDecodeError:
                self.logger.warning("remediation_parse_failed", cycle=cycle)
                break

        state.mark_stage_complete(self.stage_number)
        self.logger.info(
            "stage_complete",
            repo_url=state.github_repo_url,
            scan_passed=state.scan_result.passed if state.scan_result else False,
        )
        return state
