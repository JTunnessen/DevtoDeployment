from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console

from devtodeploy.config import Config
from devtodeploy.utils.logging import configure_logging

app = typer.Typer(
    name="devtodeploy",
    help="Multi-agent pipeline: describe an app in English, get a deployed production application.",
    add_completion=False,
)
console = Console()


def _load_config(cloud: Optional[str]) -> Config:
    config = Config()  # type: ignore[call-arg]  # pydantic-settings reads .env
    if cloud:
        from devtodeploy.config import CloudProvider
        config.cloud_provider = CloudProvider(cloud)
    return config


@app.command()
def run(
    description: str = typer.Argument(..., help="Natural language description of the application to build"),
    cloud: Optional[str] = typer.Option(None, "--cloud", "-c", help="Cloud provider: azure | gcp"),
    stages: Optional[str] = typer.Option(
        None,
        "--stages",
        help="Comma-separated stage numbers to run (e.g. 1,2,3). Runs all if omitted.",
    ),
    no_preview: bool = typer.Option(
        False,
        "--no-preview",
        help="Skip the interactive local preview loop and proceed directly to testing.",
    ),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Run the full dev-to-deployment pipeline from a natural language description.

    After code generation (Stage 2) the app is launched locally in your browser
    so you can review it and request changes before the pipeline continues.
    Use --no-preview to skip this step for automated/CI runs.
    """
    configure_logging(log_level)
    config = _load_config(cloud)

    stage_filter: list[int] | None = None
    if stages:
        try:
            stage_filter = [int(s.strip()) for s in stages.split(",")]
        except ValueError:
            console.print(f"[red]Invalid --stages value: {stages}[/]")
            raise typer.Exit(1)

    from devtodeploy.orchestrator import Orchestrator
    orchestrator = Orchestrator(config, skip_preview=no_preview)
    orchestrator.run(description, stage_filter=stage_filter)


@app.command()
def resume(
    state_path: str = typer.Argument(..., help="Path to a saved state.json file"),
    cloud: Optional[str] = typer.Option(None, "--cloud", "-c", help="Cloud provider override: azure | gcp"),
    no_preview: bool = typer.Option(
        False,
        "--no-preview",
        help="Skip the interactive local preview loop.",
    ),
    log_level: str = typer.Option("INFO", "--log-level", help="Logging level"),
) -> None:
    """Resume a previously halted or rejected pipeline from its saved state."""
    configure_logging(log_level)
    config = _load_config(cloud)

    from devtodeploy.orchestrator import Orchestrator
    orchestrator = Orchestrator(config, skip_preview=no_preview)
    orchestrator.resume(state_path, cloud_override=cloud)


@app.command()
def status(
    state_path: str = typer.Argument(..., help="Path to a saved state.json file"),
) -> None:
    """Print the current status of a pipeline run."""
    from devtodeploy.state import PipelineState, StageStatus

    state = PipelineState.load(state_path)
    stage_names = {
        1: "InputAgent",
        2: "DevelopmentAgent",
        3: "FunctionalTestAgent",
        4: "GitHubScanAgent",
        5: "ReadmeAgent",
        6: "JenkinsAgent",
        7: "CybersecAgent",
        8: "StagingAgent",
        9: "ProductionAgent",
    }
    icons = {
        StageStatus.COMPLETE: "[green]✓[/]",
        StageStatus.FAILED: "[red]✗[/]",
        StageStatus.RUNNING: "[blue]⟳[/]",
        StageStatus.SKIPPED: "[yellow]⊘[/]",
        StageStatus.PENDING: "[dim]○[/]",
    }
    console.print(f"\n[bold]Pipeline:[/] {state.pipeline_id}")
    console.print(f"[bold]App:[/] {state.app_spec.app_name if state.app_spec else '—'}")
    console.print()
    for num, name in stage_names.items():
        s = state.stage_statuses.get(num, StageStatus.PENDING)
        icon = icons.get(s, "?")
        err = f"  [red dim]{state.stage_errors.get(num, '')}[/]" if num in state.stage_errors else ""
        console.print(f"  {icon} Stage {num}: {name} ({s.value}){err}")

    # Local preview summary
    if state.local_preview_iterations:
        n = len(state.local_preview_iterations)
        console.print(
            f"\n  [cyan]↺[/] Local preview: {n} change "
            f"{'round' if n == 1 else 'rounds'} applied"
        )

    console.print()
    if state.github_repo_url:
        console.print(f"[bold]GitHub:[/] {state.github_repo_url}")
    if state.staging_deployment:
        console.print(f"[bold]Staging:[/] {state.staging_deployment.url}")
    if state.production_deployment:
        console.print(f"[bold]Production:[/] {state.production_deployment.url}")
    if state.pipeline_halted_reason:
        console.print(f"[bold yellow]Halted:[/] {state.pipeline_halted_reason}")
    console.print()


if __name__ == "__main__":
    app()
