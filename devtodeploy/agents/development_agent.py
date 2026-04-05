from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from devtodeploy.agents.base import BaseAgent, PipelineHaltException
from devtodeploy.prompts import development as prompts
from devtodeploy.state import DevIteration, DevelopmentResult, PipelineState
from devtodeploy.utils.workspace import write_app_files


class DevelopmentAgent(BaseAgent):
    name = "DevelopmentAgent"
    stage_number = 2

    def run(self, state: PipelineState) -> PipelineState:
        state.mark_stage_running(self.stage_number)
        assert state.app_spec is not None

        spec_json = state.app_spec.model_dump_json(indent=2)
        max_iter = self.config.max_dev_iterations
        iterations: list[DevIteration] = []
        issues: list[str] = []

        for i in range(1, max_iter + 1):
            self.logger.info("dev_iteration_start", iteration=i, max=max_iter)

            if i == 1:
                user_msg = prompts.initial_prompt(spec_json)
            else:
                user_msg = prompts.iteration_prompt(spec_json, issues, i)

            text = self._call_claude(
                prompts.SYSTEM,
                [{"role": "user", "content": user_msg}],
                max_tokens=16384,
            )

            files = self._parse_file_map(text)
            if not files:
                issues = ["Claude returned an empty or unparseable file map. Try again."]
                iterations.append(
                    DevIteration(
                        iteration=i,
                        files_generated={},
                        self_check_passed=False,
                        self_check_output="",
                        issues_found=issues,
                    )
                )
                continue

            app_dir = write_app_files(
                self.config.workspace_dir,
                state.pipeline_id,
                files,
            )
            check_passed, check_output, found_issues = self._self_check(app_dir, files)

            iterations.append(
                DevIteration(
                    iteration=i,
                    files_generated=files,
                    self_check_passed=check_passed,
                    self_check_output=check_output,
                    issues_found=found_issues,
                )
            )

            if check_passed:
                self.logger.info("dev_iteration_passed", iteration=i)
                entrypoint = self._detect_entrypoint(files)
                state.development_result = DevelopmentResult(
                    iterations=iterations,
                    final_files=files,
                    final_iteration=i,
                    app_entrypoint=entrypoint,
                    requirements_txt=files.get(
                        "backend/requirements.txt",
                        files.get("requirements.txt", ""),
                    ),
                )
                state.mark_stage_complete(self.stage_number)
                return state

            issues = found_issues
            self.logger.warning("dev_iteration_failed", iteration=i, issues=found_issues[:3])

        # All iterations exhausted
        last_output = iterations[-1].self_check_output if iterations else ""
        state.mark_stage_failed(
            self.stage_number,
            f"Code did not pass self-check after {max_iter} iterations. "
            f"Last output: {last_output[:500]}",
        )
        raise PipelineHaltException(
            f"DevelopmentAgent could not produce passing code in {max_iter} iterations"
        )

    def _parse_file_map(self, text: str) -> dict[str, str]:
        """Extract the JSON file map from Claude's response."""
        text = text.strip()
        # Strip markdown fences if present
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, str)}
        except json.JSONDecodeError:
            pass
        return {}

    def _self_check(
        self, app_dir: Path, files: dict[str, str]
    ) -> tuple[bool, str, list[str]]:
        """Run syntax check + basic import check. Returns (passed, output, issues)."""
        issues: list[str] = []
        outputs: list[str] = []

        # 1. Install requirements
        req_path = app_dir / "backend" / "requirements.txt"
        if not req_path.exists():
            req_path = app_dir / "requirements.txt"

        if req_path.exists():
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", str(req_path), "-q"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode != 0:
                issues.append(f"pip install failed: {result.stderr[:300]}")
                outputs.append(result.stderr)

        # 2. Syntax check every .py file
        for rel, _ in files.items():
            if not rel.endswith(".py"):
                continue
            py_file = app_dir / rel
            if not py_file.exists():
                continue
            result = subprocess.run(
                [sys.executable, "-m", "py_compile", str(py_file)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                issues.append(f"Syntax error in {rel}: {result.stderr[:200]}")
                outputs.append(result.stderr)

        passed = len(issues) == 0
        return passed, "\n".join(outputs), issues

    def _detect_entrypoint(self, files: dict[str, str]) -> str:
        for candidate in ["backend/main.py", "backend/app.py", "app/main.py", "main.py"]:
            if candidate in files:
                return candidate
        py_files = [f for f in files if f.endswith(".py")]
        return py_files[0] if py_files else "main.py"
