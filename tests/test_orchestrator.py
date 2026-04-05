"""Unit tests for the Orchestrator — stage sequencing and human approval gate."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from devtodeploy.config import Config
from devtodeploy.state import AppSpec, PipelineState, StageStatus


def make_config(**overrides) -> Config:
    defaults = dict(
        anthropic_api_key="sk-test",
        github_token="ghp_test",
        github_org="test-org",
        jenkins_url="http://your-jenkins:8080",
        jenkins_user="admin",
        jenkins_api_token="",
        workspace_dir="/tmp/test-devtodeploy",
    )
    defaults.update(overrides)
    return Config(**defaults)  # type: ignore[call-arg]


class TestHumanApprovalGate:
    def test_approve(self, monkeypatch):
        from devtodeploy.orchestrator import HumanApprovalGate
        from devtodeploy.state import DeploymentInfo, LoadTestResult

        state = PipelineState()
        state.app_spec = AppSpec(raw_description="test", app_name="TestApp")
        state.staging_deployment = DeploymentInfo(
            environment="staging",
            cloud_provider="azure",
            deployment_target="app_service",
            url="https://test.azurewebsites.net",
            load_test=LoadTestResult(
                tool="k6", max_users=100, p95_response_ms=200.0,
                error_rate_percent=0.1, passed=True
            ),
        )
        monkeypatch.setattr("builtins.input", lambda _: "approve")
        gate = HumanApprovalGate()
        assert gate.prompt(state) is True

    def test_reject(self, monkeypatch):
        from devtodeploy.orchestrator import HumanApprovalGate
        from devtodeploy.state import DeploymentInfo, LoadTestResult

        state = PipelineState()
        state.app_spec = AppSpec(raw_description="test", app_name="TestApp")
        state.staging_deployment = DeploymentInfo(
            environment="staging",
            cloud_provider="azure",
            deployment_target="app_service",
            url="https://test.azurewebsites.net",
            load_test=LoadTestResult(
                tool="k6", max_users=100, p95_response_ms=200.0,
                error_rate_percent=0.1, passed=True
            ),
        )
        monkeypatch.setattr("builtins.input", lambda _: "reject")
        gate = HumanApprovalGate()
        assert gate.prompt(state) is False

    def test_invalid_then_approve(self, monkeypatch):
        from devtodeploy.orchestrator import HumanApprovalGate

        state = PipelineState()
        state.app_spec = AppSpec(raw_description="test", app_name="TestApp")
        state.staging_deployment = None

        responses = iter(["yes", "nope", "approve"])
        monkeypatch.setattr("builtins.input", lambda _: next(responses))
        gate = HumanApprovalGate()
        assert gate.prompt(state) is True


class TestJenkinsIsPlaceholder:
    def test_placeholder_url_detected(self):
        config = make_config()
        assert config.jenkins_is_placeholder is True

    def test_empty_token_detected(self):
        config = make_config(
            jenkins_url="http://real-jenkins:8080",
            jenkins_api_token="",
        )
        assert config.jenkins_is_placeholder is True

    def test_configured_jenkins(self):
        config = make_config(
            jenkins_url="http://real-jenkins:8080",
            jenkins_api_token="abc123",
        )
        assert config.jenkins_is_placeholder is False


class TestPipelineStateResume:
    def test_resume_detects_approval_rejected(self, tmp_path):
        """A state with stage 8 complete and human_approved=False should restart from stage 8."""
        state = PipelineState()
        state.app_spec = AppSpec(raw_description="test app", app_name="TestApp")
        state.mark_stage_complete(8)
        state.human_approved = False
        state.pipeline_halted_reason = "Rejected at QA gate"
        state.save(str(tmp_path))

        loaded = PipelineState.load(str(tmp_path / "state.json"))
        assert loaded.stage_statuses[8] == StageStatus.COMPLETE
        assert loaded.human_approved is False

    def test_resume_detects_approval_pending(self, tmp_path):
        """A state where staging completed but human_approved is None should re-show the gate."""
        state = PipelineState()
        state.mark_stage_complete(8)
        state.human_approved = None
        state.save(str(tmp_path))

        loaded = PipelineState.load(str(tmp_path / "state.json"))
        assert loaded.human_approved is None
