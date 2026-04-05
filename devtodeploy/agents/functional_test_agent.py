from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from devtodeploy.agents.base import BaseAgent
from devtodeploy.prompts import testing as prompts
from devtodeploy.state import PipelineState
from devtodeploy.utils.workspace import write_app_files


class FunctionalTestAgent(BaseAgent):
    name = "FunctionalTestAgent"
    stage_number = 3

    def run(self, state: PipelineState) -> PipelineState:
        state.mark_stage_running(self.stage_number)
        assert state.development_result is not None
        assert state.app_spec is not None

        source_files = state.development_result.final_files
        source_summary = self._build_source_summary(source_files)
        spec_json = state.app_spec.model_dump_json(indent=2)

        # Retry up to 3 times if Claude returns an empty or unparseable response
        test_files: dict[str, str] = {}
        for attempt in range(1, 4):
            text = self._call_claude(
                prompts.SYSTEM,
                [{"role": "user", "content": prompts.user_prompt(source_summary, spec_json)}],
                max_tokens=8096,
            )
            test_files = self._parse_file_map(text)
            if test_files:
                break
            self.logger.warning(
                "test_files_empty", attempt=attempt,
                hint="Claude returned no parseable test files — retrying."
            )

        if not test_files:
            # Non-fatal: log warning, mark skipped, and continue the pipeline
            self.logger.warning(
                "test_generation_failed",
                reason="Claude did not return test files after 3 attempts — skipping.",
            )
            state.mark_stage_skipped(
                self.stage_number,
                "Could not generate test files after 3 attempts — continuing pipeline.",
            )
            return state

        # Write test files into the app workspace
        write_app_files(self.config.workspace_dir, state.pipeline_id, test_files)
        app_dir = Path(self.config.workspace_dir) / state.pipeline_id / "app"

        passed, pass_rate = self._run_tests(app_dir)
        state.test_files = test_files

        if not passed:
            self.logger.warning(
                "test_pass_rate_below_threshold", pass_rate=pass_rate
            )

        state.mark_stage_complete(self.stage_number)
        self.logger.info("tests_written", file_count=len(test_files), pass_rate=pass_rate)
        return state

    def _parse_file_map(self, text: str) -> dict[str, str]:
        text = text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        # Find the first { and last } in case there is surrounding text
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            text = text[start:end + 1]
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, str)}
        except json.JSONDecodeError:
            pass
        return {}

    def _run_tests(self, app_dir: Path) -> tuple[bool, float]:
        """Run pytest and return (pass_rate >= 0.8, pass_rate)."""
        result = subprocess.run(
            [
                sys.executable, "-m", "pytest",
                str(app_dir / "tests"),
                "--tb=short", "-q",
                "--no-header",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(app_dir),
        )
        output = result.stdout + result.stderr
        passed_count = failed_count = 0
        for line in output.splitlines():
            if "passed" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p == "passed" and i > 0:
                        try:
                            passed_count = int(parts[i - 1])
                        except ValueError:
                            pass
                    if p == "failed" and i > 0:
                        try:
                            failed_count = int(parts[i - 1])
                        except ValueError:
                            pass
        total = passed_count + failed_count
        rate = passed_count / total if total > 0 else 0.0
        self.logger.info(
            "pytest_results",
            passed=passed_count,
            failed=failed_count,
            rate=round(rate, 2),
        )
        return rate >= 0.8, rate

    def _build_source_summary(self, files: dict[str, str]) -> str:
        parts: list[str] = []
        for path, content in files.items():
            lines = content.splitlines()[:40]
            if path.endswith(".py"):
                parts.append(f"### {path}\n" + "\n".join(lines))
            else:
                parts.append(f"### {path}  ({len(content.splitlines())} lines)")
        return "\n\n".join(parts)
