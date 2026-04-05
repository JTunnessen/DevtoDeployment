from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from devtodeploy.agents.base import PipelineHaltException
from devtodeploy.agents.cybersec_agent import CybersecAgent
from devtodeploy.agents.development_agent import DevelopmentAgent
from devtodeploy.agents.functional_test_agent import FunctionalTestAgent
from devtodeploy.agents.github_scan_agent import GitHubScanAgent
from devtodeploy.agents.input_agent import InputAgent
from devtodeploy.agents.jenkins_agent import JenkinsAgent
from devtodeploy.agents.production_agent import ProductionAgent
from devtodeploy.agents.readme_agent import ReadmeAgent
from devtodeploy.agents.staging_agent import StagingAgent
from devtodeploy.config import Config
from devtodeploy.local_preview import LocalPreviewGate
from devtodeploy.state import AppSpec, PipelineState, StageStatus
from devtodeploy.utils.logging import get_logger
from devtodeploy.utils.workspace import ensure_workspace

if TYPE_CHECKING:
    pass

console = Console()
logger = get_logger("orchestrator")

PIPELINE_STAGES = [
    InputAgent,           # 1
    DevelopmentAgent,     # 2
    FunctionalTestAgent,  # 3
    GitHubScanAgent,      # 4
    ReadmeAgent,          # 5
    JenkinsAgent,         # 6
    CybersecAgent,        # 7
    StagingAgent,         # 8
    # ProductionAgent (9) is triggered after human approval
]


class HumanApprovalGate:
    """Pause the pipeline and ask the operator to approve or reject staging."""

    def prompt(self, state: PipelineState) -> bool:
        deploy = state.staging_deployment
        lt = deploy.load_test if deploy else None
        scan = state.scan_result
        jenkins = state.jenkins_result

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_row("App", state.app_spec.app_name if state.app_spec else "—")
        table.add_row(
            "Staging URL",
            f"[bold cyan]{deploy.url}[/]" if deploy else "—",
        )
        if lt:
            status_icon = "[green]✓ PASSED[/]" if lt.passed else "[red]✗ FAILED[/]"
            table.add_row(
                "Load Test",
                f"{status_icon}  (p95={lt.p95_response_ms:.0f}ms, "
                f"error rate={lt.error_rate_percent:.1f}%)",
            )
        if scan:
            scan_icon = "[green]✓ PASSED[/]" if scan.passed else "[yellow]⚠ WARNINGS[/]"
            table.add_row(
                "Static Scan",
                f"{scan_icon}  (HIGH={scan.high_count}, MED={scan.medium_count}, "
                f"LOW={scan.low_count})",
            )
        if jenkins:
            j_icon = "[green]✓ SUCCESS[/]" if jenkins.status == "SUCCESS" else "[red]✗ FAILED[/]"
            table.add_row(
                "Jenkins",
                f"{j_icon}  ({jenkins.test_passed}/{jenkins.test_total} tests passed)",
            )
        else:
            table.add_row("Jenkins", "[dim]Skipped (not configured)[/]")

        console.print()
        console.print(
            Panel(
                table,
                title="[bold yellow]STAGING QA APPROVAL REQUIRED[/]",
                subtitle="[dim]Test the application at the URL above, then decide[/]",
                border_style="yellow",
                padding=(1, 2),
            )
        )
        console.print()
        console.print(
            "  Type [bold green]approve[/] to deploy to production.\n"
            "  Type [bold red]reject[/]  to shut down staging and stop the pipeline."
        )
        console.print()

        while True:
            try:
                answer = input("  Your decision > ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[red]Interrupted — treating as reject.[/]")
                return False
            if answer == "approve":
                return True
            if answer == "reject":
                return False
            console.print("  Please type [bold]approve[/] or [bold]reject[/].")


class Orchestrator:
    def __init__(self, config: Config, skip_preview: bool = False) -> None:
        self.config = config
        self.skip_preview = skip_preview
        self.agents = [AgentClass(config) for AgentClass in PIPELINE_STAGES]
        self.production_agent = ProductionAgent(config)

    def run(
        self,
        description: str,
        stage_filter: list[int] | None = None,
        cloud_override: str | None = None,
    ) -> PipelineState:
        """Run the full pipeline from scratch."""
        if cloud_override:
            from devtodeploy.config import CloudProvider
            self.config.cloud_provider = CloudProvider(cloud_override)

        state = PipelineState(config_snapshot=self.config.model_dump(mode="json"))
        state.app_spec = AppSpec(raw_description=description)
        ensure_workspace(self.config.workspace_dir, state.pipeline_id)

        return self._execute(state, stage_filter=stage_filter)

    def resume(self, state_path: str, cloud_override: str | None = None) -> PipelineState:
        """Resume a previously halted pipeline from its saved state."""
        state = PipelineState.load(state_path)
        logger.info("resuming_pipeline", pipeline_id=state.pipeline_id, stage=state.current_stage)

        if cloud_override:
            from devtodeploy.config import CloudProvider
            self.config.cloud_provider = CloudProvider(cloud_override)

        # If halted at approval gate (stage 8 complete, approval rejected/None)
        # restart from stage 8 to re-provision staging
        start_from = state.current_stage
        if (
            state.stage_statuses.get(8) == StageStatus.COMPLETE
            and state.human_approved is not True
        ):
            start_from = 7  # re-run from stage 8 (0-indexed: index 7)
            state.staging_deployment = None
            state.human_approved = None

        return self._execute(state, start_stage_number=start_from + 1)

    def _execute(
        self,
        state: PipelineState,
        stage_filter: list[int] | None = None,
        start_stage_number: int = 1,
    ) -> PipelineState:
        save_path = (
            Path(self.config.workspace_dir) / state.pipeline_id / "state.json"
        )

        # Run stages 1–8
        for agent in self.agents:
            if agent.stage_number < start_stage_number:
                continue
            if stage_filter and agent.stage_number not in stage_filter:
                logger.info("stage_filtered_out", stage=agent.stage_number)
                continue

            console.rule(
                f"[bold blue]Stage {agent.stage_number}: {agent.name}[/]",
                style="blue",
            )
            try:
                state = agent.run(state)
                state.save(str(save_path.parent))
                self._print_stage_status(agent.stage_number, agent.name, state)
            except PipelineHaltException as exc:
                console.print(f"\n[bold red]Pipeline halted at Stage {agent.stage_number}[/]")
                console.print(f"[red]{exc}[/]")
                console.print(f"\nState saved to: {save_path}")
                console.print(
                    f"To resume: devtodeploy resume {save_path}"
                )
                state.save(str(save_path.parent))
                return state

            # After Stage 2 (DevelopmentAgent), run the interactive local preview
            # loop so the creator can review the app and request changes before
            # the pipeline continues to testing and deployment.
            if (
                agent.stage_number == 2
                and not self.skip_preview
                and not state.local_preview_completed
            ):
                console.rule("[bold cyan]Local Preview & Iterative Refinement[/]", style="cyan")
                try:
                    preview = LocalPreviewGate(self.config)
                    state = preview.run(state)
                    state.save(str(save_path.parent))
                    n = len(state.local_preview_iterations)
                    console.print(
                        f"  [cyan]✓[/] Local preview complete "
                        f"({n} change {'round' if n == 1 else 'rounds'} applied)"
                    )
                except Exception as exc:
                    # Non-fatal: log the error and continue the pipeline
                    logger.warning("local_preview_error", error=str(exc))
                    console.print(
                        f"  [yellow]⚠ Local preview encountered an error and was skipped: {exc}[/]"
                    )

        # Stop here if stage_filter doesn't include stage 9
        if stage_filter and 9 not in stage_filter:
            return state

        # Human approval gate (only if staging ran)
        if state.stage_statuses.get(8) == StageStatus.COMPLETE:
            gate = HumanApprovalGate()
            approved = gate.prompt(state)
            state.human_approved = approved

            if not approved:
                console.print("\n[yellow]QA rejected. Tearing down staging environment…[/]")
                self._destroy_staging(state)
                console.print("[yellow]Staging torn down. Pipeline stopped.[/]")
                console.print(
                    f"\n[dim]State saved to {save_path}[/]\n"
                    f"[dim]To restart: devtodeploy resume {save_path}[/]"
                )
                state.pipeline_halted_reason = "Rejected at QA approval gate"
                state.save(str(save_path.parent))
                return state

        # Stage 9 — Production
        if not stage_filter or 9 in stage_filter:
            console.rule("[bold blue]Stage 9: ProductionAgent[/]", style="blue")
            try:
                state = self.production_agent.run(state)
                state.save(str(save_path.parent))
                self._print_stage_status(9, "ProductionAgent", state)
            except PipelineHaltException as exc:
                console.print(f"\n[bold red]Pipeline halted at Stage 9[/]")
                console.print(f"[red]{exc}[/]")
                state.save(str(save_path.parent))
                return state

        self._print_final_summary(state)
        return state

    def _destroy_staging(self, state: PipelineState) -> None:
        """Run terraform destroy on the staging environment."""
        from devtodeploy.integrations.terraform_runner import TerraformRunner
        tf_dir = (
            Path(self.config.workspace_dir) / state.pipeline_id / "terraform" / "staging"
        )
        if not tf_dir.exists():
            return
        try:
            tf = TerraformRunner(str(tf_dir))
            tf.destroy({})
        except Exception as exc:
            logger.warning("staging_destroy_failed", error=str(exc))

    def _print_stage_status(self, stage: int, name: str, state: PipelineState) -> None:
        status = state.stage_statuses.get(stage, StageStatus.PENDING)
        icon = {
            StageStatus.COMPLETE: "[green]✓[/]",
            StageStatus.FAILED: "[red]✗[/]",
            StageStatus.SKIPPED: "[yellow]⊘[/]",
        }.get(status, "?")
        console.print(f"  {icon} Stage {stage} ({name}): {status.value}")

    def _print_final_summary(self, state: PipelineState) -> None:
        console.print()
        console.print(
            Panel(
                f"[bold green]Pipeline Complete![/]\n\n"
                f"App: [bold]{state.app_spec.app_name if state.app_spec else '—'}[/]\n"
                f"GitHub: {state.github_repo_url or '—'}\n"
                f"Staging: {state.staging_deployment.url if state.staging_deployment else '—'}\n"
                f"Production: {state.production_deployment.url if state.production_deployment else '—'}",
                title="[bold green]SUCCESS[/]",
                border_style="green",
            )
        )
