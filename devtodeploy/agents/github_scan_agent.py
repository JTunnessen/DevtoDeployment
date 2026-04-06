from __future__ import annotations

import json
from pathlib import Path

from devtodeploy.agents.base import BaseAgent, PipelineHaltException
from devtodeploy.integrations.bandit_runner import BanditRunner
from devtodeploy.integrations.docker_builder import DockerBuilder
from devtodeploy.integrations.github_client import GitHubClient
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
        scanner = BanditRunner()
        app_dir = Path(self.config.workspace_dir) / state.pipeline_id / "app"

        # Create GitHub repo
        repo = gh.create_repo(
            name=state.app_spec.suggested_repo_name,
            description=state.app_spec.raw_description[:255],
            private=False,
        )
        state.github_repo_name = repo.name
        state.github_repo_url = repo.html_url

        # Ensure .gitignore exists so .env is never committed to the generated repo
        self._ensure_gitignore(app_dir)

        # Push code
        gh.push_directory(repo, str(app_dir), commit_msg="feat: initial generated application")
        self.logger.info("code_pushed", url=state.github_repo_url)

        # Semgrep scan + auto-remediation loop (up to 3 cycles)
        for cycle in range(1, 4):
            req_file = state.development_result.requirements_txt and str(
                next(
                    (
                        app_dir / p
                        for p in ("backend/requirements.txt", "requirements.txt")
                        if (app_dir / p).exists()
                    ),
                    "",
                )
            )
            scan = scanner.run(str(app_dir), requirements_file=req_file or "")
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

        # Build and push Docker image once here — Stages 8 and 9 reuse it
        self._build_docker_image(state, app_dir)

        state.mark_stage_complete(self.stage_number)
        self.logger.info(
            "stage_complete",
            repo_url=state.github_repo_url,
            docker_image=state.docker_image_uri,
            scan_passed=state.scan_result.passed if state.scan_result else False,
        )
        return state

    def _build_docker_image(self, state: PipelineState, app_dir: Path) -> None:
        """Build and push the app Docker image; store URI in state for reuse."""
        assert state.app_spec is not None
        from devtodeploy.config import CloudProvider
        app_name = state.app_spec.suggested_repo_name.replace("_", "-").lower()
        try:
            docker = DockerBuilder()
            if self.config.cloud_provider == CloudProvider.GCP:
                uri = docker.build_and_push_gcp(
                    str(app_dir),
                    self.config.gcp_project_id,
                    app_name,
                    tag="latest",
                )
            else:
                registry = getattr(self.config, "azure_container_registry", "")
                uri = docker.build_and_push_azure(str(app_dir), registry, app_name, tag="latest")
            state.docker_image_uri = uri
            self.logger.info("docker_image_built", uri=uri)
        except Exception as exc:
            self.logger.warning("docker_build_skipped", reason=str(exc))

    # ------------------------------------------------------------------

    _GITIGNORE_CONTENT = """\
# Environment — never commit secrets
.env
.env.*
!.env.example

# Python
__pycache__/
*.py[cod]
*.pyo
*.egg-info/
dist/
build/
.venv/
venv/
env/

# Testing
.pytest_cache/
.coverage
htmlcov/

# Editors
.vscode/
.idea/
*.swp
*~

# OS
.DS_Store
Thumbs.db
"""

    def _ensure_gitignore(self, app_dir: Path) -> None:
        """Write a .gitignore to app_dir if one isn't already present."""
        gitignore_path = app_dir / ".gitignore"
        if gitignore_path.exists():
            # Make sure .env is in it; append if missing
            existing = gitignore_path.read_text(encoding="utf-8")
            if ".env" not in existing:
                with gitignore_path.open("a", encoding="utf-8") as f:
                    f.write("\n# Environment — never commit secrets\n.env\n.env.*\n!.env.example\n")
                self.logger.info("gitignore_env_appended")
        else:
            gitignore_path.write_text(self._GITIGNORE_CONTENT, encoding="utf-8")
            self.logger.info("gitignore_created")
