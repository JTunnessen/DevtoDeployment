from __future__ import annotations

import json

from devtodeploy.agents.base import BaseAgent, PipelineHaltException
from devtodeploy.prompts import input_analysis as prompts
from devtodeploy.state import AppSpec, PipelineState


class InputAgent(BaseAgent):
    name = "InputAgent"
    stage_number = 1

    def run(self, state: PipelineState) -> PipelineState:
        state.mark_stage_running(self.stage_number)
        self.logger.info("parsing_description")

        raw = state.app_spec.raw_description if state.app_spec else ""
        if not raw.strip():
            state.mark_stage_failed(self.stage_number, "No application description provided")
            raise PipelineHaltException("No application description provided")

        last_error: str = ""
        for attempt in range(1, 4):
            messages: list[dict] = [{"role": "user", "content": prompts.user_prompt(raw)}]
            if last_error:
                messages.append(
                    {
                        "role": "assistant",
                        "content": last_error,
                    }
                )
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            f"That response was invalid JSON or didn't match the schema. "
                            f"Error: {last_error}. Please return ONLY the JSON object."
                        ),
                    }
                )

            text = self._call_claude(prompts.SYSTEM, messages, max_tokens=2048)

            try:
                data = json.loads(text.strip())
                app_spec = AppSpec(
                    raw_description=raw,
                    app_name=data.get("app_name", "MyApp"),
                    app_type=data.get("app_type", "fullstack_web"),
                    backend_framework=data.get("backend_framework", "fastapi"),
                    frontend_type=data.get("frontend_type", "html_js"),
                    features=data.get("features", []),
                    constraints=data.get("constraints", []),
                    suggested_repo_name=data.get("suggested_repo_name", "my-app"),
                )
                state.app_spec = app_spec
                state.mark_stage_complete(self.stage_number)
                self.logger.info(
                    "app_spec_parsed",
                    app_name=app_spec.app_name,
                    repo=app_spec.suggested_repo_name,
                    features=len(app_spec.features),
                )
                return state
            except (json.JSONDecodeError, KeyError) as exc:
                last_error = str(exc)
                self.logger.warning("json_parse_failed", attempt=attempt, error=last_error)

        state.mark_stage_failed(self.stage_number, f"Failed to parse app spec after 3 attempts: {last_error}")
        raise PipelineHaltException("InputAgent could not parse a valid AppSpec from Claude's response")
