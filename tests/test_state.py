"""Unit tests for devtodeploy.state — serialization and stage tracking."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from devtodeploy.state import (
    AppSpec,
    DevelopmentResult,
    DevIteration,
    JenkinsResult,
    PipelineState,
    ScanResult,
    StageStatus,
)


def make_state() -> PipelineState:
    state = PipelineState()
    state.app_spec = AppSpec(
        raw_description="A simple to-do app",
        app_name="TodoApp",
        suggested_repo_name="todo-app",
        features=["add tasks", "mark complete"],
    )
    return state


class TestPipelineStateCreation:
    def test_default_values(self):
        state = PipelineState()
        assert state.current_stage == 0
        assert state.stage_statuses == {}
        assert state.human_approved is None

    def test_pipeline_id_is_uuid(self):
        state = PipelineState()
        assert len(state.pipeline_id) == 36
        assert state.pipeline_id.count("-") == 4

    def test_two_states_have_different_ids(self):
        s1 = PipelineState()
        s2 = PipelineState()
        assert s1.pipeline_id != s2.pipeline_id


class TestStageTracking:
    def test_mark_running(self):
        state = make_state()
        state.mark_stage_running(1)
        assert state.current_stage == 1
        assert state.stage_statuses[1] == StageStatus.RUNNING

    def test_mark_complete(self):
        state = make_state()
        state.mark_stage_running(1)
        state.mark_stage_complete(1)
        assert state.stage_statuses[1] == StageStatus.COMPLETE

    def test_mark_failed(self):
        state = make_state()
        state.mark_stage_failed(2, "Some error")
        assert state.stage_statuses[2] == StageStatus.FAILED
        assert state.stage_errors[2] == "Some error"

    def test_mark_skipped(self):
        state = make_state()
        state.mark_stage_skipped(6, "Jenkins not configured")
        assert state.stage_statuses[6] == StageStatus.SKIPPED
        assert "Jenkins" in state.stage_errors[6]


class TestSerialization:
    def test_save_and_load(self, tmp_path):
        state = make_state()
        state.mark_stage_complete(1)
        state.github_repo_url = "https://github.com/org/todo-app"
        state.readme_content = "# TodoApp"

        state.save(str(tmp_path))

        state_file = tmp_path / "state.json"
        assert state_file.exists()

        loaded = PipelineState.load(str(state_file))
        assert loaded.pipeline_id == state.pipeline_id
        assert loaded.app_spec is not None
        assert loaded.app_spec.app_name == "TodoApp"
        assert loaded.stage_statuses[1] == StageStatus.COMPLETE
        assert loaded.github_repo_url == "https://github.com/org/todo-app"
        assert loaded.readme_content == "# TodoApp"

    def test_json_is_valid(self, tmp_path):
        state = make_state()
        state.save(str(tmp_path))
        raw = (tmp_path / "state.json").read_text()
        data = json.loads(raw)
        assert "pipeline_id" in data
        assert "app_spec" in data

    def test_nested_models_round_trip(self, tmp_path):
        state = make_state()
        state.development_result = DevelopmentResult(
            final_files={"backend/main.py": "print('hello')"},
            app_entrypoint="backend/main.py",
            requirements_txt="fastapi\n",
            iterations=[
                DevIteration(
                    iteration=1,
                    files_generated={"backend/main.py": "print('hello')"},
                    self_check_passed=True,
                )
            ],
        )
        state.scan_result = ScanResult(high_count=0, medium_count=1, low_count=3, passed=True)
        state.jenkins_result = JenkinsResult(
            build_number=42, status="SUCCESS", test_passed=15, test_failed=0
        )
        state.save(str(tmp_path))

        loaded = PipelineState.load(str(tmp_path / "state.json"))
        assert loaded.development_result is not None
        assert loaded.development_result.final_files["backend/main.py"] == "print('hello')"
        assert loaded.scan_result is not None
        assert loaded.scan_result.medium_count == 1
        assert loaded.jenkins_result is not None
        assert loaded.jenkins_result.build_number == 42

    def test_human_approval_round_trip(self, tmp_path):
        state = make_state()
        state.human_approved = True
        state.save(str(tmp_path))
        loaded = PipelineState.load(str(tmp_path / "state.json"))
        assert loaded.human_approved is True
