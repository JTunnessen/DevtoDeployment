from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    SKIPPED = "skipped"


# ---------------------------------------------------------------------------
# Stage-specific output models
# ---------------------------------------------------------------------------

class AppSpec(BaseModel):
    raw_description: str
    app_name: str = ""
    app_type: str = "fullstack_web"
    backend_framework: str = "fastapi"
    frontend_type: str = "html_js"
    features: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    suggested_repo_name: str = ""


class DevIteration(BaseModel):
    iteration: int
    files_generated: dict[str, str] = Field(default_factory=dict)
    self_check_passed: bool = False
    self_check_output: str = ""
    issues_found: list[str] = Field(default_factory=list)


class DevelopmentResult(BaseModel):
    iterations: list[DevIteration] = Field(default_factory=list)
    final_files: dict[str, str] = Field(default_factory=dict)
    final_iteration: int = 0
    app_entrypoint: str = "backend/main.py"
    requirements_txt: str = ""


class ScanFinding(BaseModel):
    rule_id: str
    severity: str
    message: str
    path: str
    line: int = 0


class ScanResult(BaseModel):
    tool: str = "semgrep"
    findings: list[ScanFinding] = Field(default_factory=list)
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    passed: bool = True
    remediation_cycles: int = 0


class JenkinsResult(BaseModel):
    build_number: int = 0
    build_url: str = ""
    status: str = "UNKNOWN"
    test_total: int = 0
    test_passed: int = 0
    test_failed: int = 0
    duration_seconds: float = 0.0


class LoadTestResult(BaseModel):
    tool: str = "k6"
    max_users: int = 0
    p95_response_ms: float = 0.0
    avg_response_ms: float = 0.0
    error_rate_percent: float = 0.0
    requests_per_second: float = 0.0
    passed: bool = False


class DeploymentInfo(BaseModel):
    environment: str
    cloud_provider: str
    deployment_target: str
    url: str = ""
    terraform_outputs: dict[str, str] = Field(default_factory=dict)
    load_test: LoadTestResult | None = None


class NistControlAssessment(BaseModel):
    control_family: str
    control_id: str
    title: str
    status: str  # Implemented | Partially Implemented | Not Applicable | Planned
    implementation_notes: str = ""
    gaps: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level pipeline state
# ---------------------------------------------------------------------------

class PipelineState(BaseModel):
    pipeline_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    current_stage: int = 0
    stage_statuses: dict[int, StageStatus] = Field(default_factory=dict)
    stage_errors: dict[int, str] = Field(default_factory=dict)

    # Stage outputs
    app_spec: AppSpec | None = None
    development_result: DevelopmentResult | None = None
    test_files: dict[str, str] = Field(default_factory=dict)
    github_repo_url: str = ""
    github_repo_name: str = ""
    scan_result: ScanResult | None = None
    readme_content: str = ""
    jenkins_result: JenkinsResult | None = None
    cybersec_doc_content: str = ""
    nist_doc_content: str = ""
    nist_assessments: list[NistControlAssessment] = Field(default_factory=list)
    staging_deployment: DeploymentInfo | None = None
    production_deployment: DeploymentInfo | None = None

    # Human approval gate
    human_approved: bool | None = None
    pipeline_halted_reason: str = ""

    # ---------------------------------------------------------------------------

    def save(self, workspace_dir: str) -> None:
        path = Path(workspace_dir) / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, path: str) -> "PipelineState":
        return cls.model_validate_json(Path(path).read_text())

    def mark_stage_running(self, stage: int) -> None:
        self.current_stage = stage
        self.stage_statuses[stage] = StageStatus.RUNNING
        self.updated_at = datetime.utcnow()

    def mark_stage_complete(self, stage: int) -> None:
        self.stage_statuses[stage] = StageStatus.COMPLETE
        self.updated_at = datetime.utcnow()

    def mark_stage_failed(self, stage: int, error: str) -> None:
        self.stage_statuses[stage] = StageStatus.FAILED
        self.stage_errors[stage] = error
        self.updated_at = datetime.utcnow()

    def mark_stage_skipped(self, stage: int, reason: str = "") -> None:
        self.stage_statuses[stage] = StageStatus.SKIPPED
        if reason:
            self.stage_errors[stage] = reason
        self.updated_at = datetime.utcnow()
