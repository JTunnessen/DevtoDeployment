from __future__ import annotations

import json
from datetime import date

from devtodeploy.agents.base import BaseAgent
from devtodeploy.integrations.github_client import GitHubClient
from devtodeploy.prompts import cybersec as sec_prompts
from devtodeploy.prompts import nist_800_53 as nist_prompts
from devtodeploy.state import PipelineState


class CybersecAgent(BaseAgent):
    name = "CybersecAgent"
    stage_number = 7

    def run(self, state: PipelineState) -> PipelineState:
        state.mark_stage_running(self.stage_number)
        assert state.development_result is not None
        assert state.app_spec is not None

        spec_json = state.app_spec.model_dump_json(indent=2)
        source_summary = self._build_source_summary(state)
        scan_findings_json = self._build_scan_json(state)
        jenkins_summary = self._build_jenkins_summary(state)
        today = str(date.today())

        # --- Generate SECURITY.md ---
        self.logger.info("generating_security_md")
        security_md = self._call_claude(
            sec_prompts.SYSTEM,
            [
                {
                    "role": "user",
                    "content": sec_prompts.user_prompt(
                        spec_json, source_summary, scan_findings_json, jenkins_summary
                    ),
                }
            ],
            max_tokens=8096,
        )
        state.cybersec_doc_content = security_md

        # --- Generate NIST_800_53.md ---
        self.logger.info("generating_nist_800_53_md")
        nist_md = self._call_claude(
            nist_prompts.SYSTEM,
            [
                {
                    "role": "user",
                    "content": nist_prompts.user_prompt(
                        spec_json, source_summary, scan_findings_json, today
                    ),
                }
            ],
            max_tokens=16384,
        )
        state.nist_doc_content = nist_md

        # --- Push both docs to GitHub ---
        gh = GitHubClient(self.config.github_token, self.config.github_org)
        repo = gh.get_repo_from_url(state.github_repo_url)

        gh.create_or_update_file(
            repo,
            "SECURITY.md",
            security_md,
            "docs: add SECURITY.md and NIST_800_53.md cybersecurity documentation",
        )
        gh.create_or_update_file(
            repo,
            "NIST_800_53.md",
            nist_md,
            "docs: update NIST_800_53.md",
        )

        state.mark_stage_complete(self.stage_number)
        self.logger.info(
            "cybersec_docs_pushed",
            repo=state.github_repo_name,
            security_md_len=len(security_md),
            nist_md_len=len(nist_md),
        )
        return state

    def _build_source_summary(self, state: PipelineState) -> str:
        """Return file list + first 20 lines of each Python file."""
        parts: list[str] = []
        for path, content in state.development_result.final_files.items():  # type: ignore[union-attr]
            lines = content.splitlines()
            if path.endswith(".py"):
                parts.append(f"### {path}\n" + "\n".join(lines[:20]))
            else:
                parts.append(f"### {path}  ({len(lines)} lines)")
        return "\n\n".join(parts)

    def _build_scan_json(self, state: PipelineState) -> str:
        if not state.scan_result:
            return "[]"
        return json.dumps(
            [f.model_dump() for f in state.scan_result.findings],
            indent=2,
        )

    def _build_jenkins_summary(self, state: PipelineState) -> str:
        if not state.jenkins_result:
            return "Jenkins not run (not configured)."
        jr = state.jenkins_result
        return (
            f"Status: {jr.status}, "
            f"Tests: {jr.test_passed} passed / {jr.test_failed} failed, "
            f"Duration: {jr.duration_seconds:.0f}s"
        )
