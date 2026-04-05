from __future__ import annotations

import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

import anthropic
import httpx
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from devtodeploy.prompts import development as prompts
from devtodeploy.state import DevelopmentResult, LocalPreviewIteration, PipelineState
from devtodeploy.utils.logging import get_logger
from devtodeploy.utils.workspace import write_app_files

if TYPE_CHECKING:
    from devtodeploy.config import Config

console = Console()
logger = get_logger("local_preview")

_PREVIEW_PORT = 8765
_SERVER_READY_TIMEOUT = 45  # seconds to wait for the server to accept connections
_HEALTH_URL = f"http://127.0.0.1:{_PREVIEW_PORT}/health"
_ROOT_URL = f"http://127.0.0.1:{_PREVIEW_PORT}/"


class LocalPreviewGate:
    """
    After Stage 2 (DevelopmentAgent), spin up the generated application locally,
    open the browser, and let the creator request iterative changes before the
    pipeline continues to Stage 3.
    """

    def __init__(self, config: "Config") -> None:
        self.config = config
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, state: PipelineState) -> PipelineState:
        assert state.development_result is not None
        assert state.app_spec is not None

        app_dir = Path(self.config.workspace_dir) / state.pipeline_id / "app"
        preview_round = 0

        console.print()
        console.print(
            Panel(
                "[bold]Local Preview[/bold]\n\n"
                "Your generated application will launch in your browser.\n"
                "Review it, request changes if needed, and type [bold green]no[/] "
                "when you're happy to continue the pipeline.",
                border_style="cyan",
                title="[bold cyan]INTERACTIVE PREVIEW[/]",
            )
        )

        while True:
            preview_round += 1
            server_proc = self._start_server(state, app_dir)

            try:
                ready = self._wait_for_server()
                if not ready:
                    console.print(
                        "[yellow]Warning: server did not respond on "
                        f"http://127.0.0.1:{_PREVIEW_PORT} within "
                        f"{_SERVER_READY_TIMEOUT}s — opening browser anyway.[/]"
                    )

                console.print(
                    f"\n  [bold cyan]App running at[/] "
                    f"[link=http://127.0.0.1:{_PREVIEW_PORT}]"
                    f"http://127.0.0.1:{_PREVIEW_PORT}[/link]\n"
                )
                webbrowser.open(_ROOT_URL)

                # Ask the creator if they want changes
                wants_changes = Confirm.ask(
                    "\n  Would you like to make any changes or enhancements?",
                    default=False,
                )

                if not wants_changes:
                    console.print(
                        "\n  [green]Great! Continuing to the next pipeline stage…[/]\n"
                    )
                    break

                # Collect one or more change requests
                change_requests = self._collect_change_requests()

            finally:
                self._stop_server(server_proc)

            # Apply changes via Claude
            files_before = list(state.development_result.final_files.keys())
            console.print("\n  [dim]Applying your changes — please wait…[/]\n")
            updated_files = self._apply_changes(state, change_requests)

            if updated_files:
                state.development_result.final_files = updated_files
                write_app_files(self.config.workspace_dir, state.pipeline_id, updated_files)
                files_after = list(updated_files.keys())
            else:
                console.print(
                    "  [yellow]Claude returned an unparseable response — "
                    "keeping the previous version.[/]"
                )
                files_after = files_before

            state.local_preview_iterations.append(
                LocalPreviewIteration(
                    iteration=preview_round,
                    change_request="\n".join(change_requests),
                    files_before=files_before,
                    files_after=files_after,
                )
            )

        state.local_preview_completed = True
        return state

    # ------------------------------------------------------------------
    # Change collection
    # ------------------------------------------------------------------

    def _collect_change_requests(self) -> list[str]:
        """Prompt the creator to enter one or more change requests."""
        console.print(
            "\n  Enter your change requests below.\n"
            "  Press [bold]Enter[/] after each one.\n"
            "  Type [bold]done[/] on a blank line when finished.\n"
        )
        requests: list[str] = []
        idx = 1
        while True:
            entry = Prompt.ask(f"  Change {idx}").strip()
            if entry.lower() in ("done", ""):
                if not requests:
                    console.print("  [yellow]Please enter at least one change.[/]")
                    continue
                break
            requests.append(entry)
            idx += 1
            console.print(
                "  [dim](Enter another change or type [bold]done[/] to finish)[/]"
            )
        return requests

    # ------------------------------------------------------------------
    # Claude: apply changes
    # ------------------------------------------------------------------

    def _apply_changes(
        self, state: PipelineState, change_requests: list[str]
    ) -> dict[str, str]:
        assert state.development_result is not None
        assert state.app_spec is not None

        current_files_json = json.dumps(
            state.development_result.final_files, indent=2
        )
        spec_json = state.app_spec.model_dump_json(indent=2)

        response = self.client.messages.create(
            model=self.config.claude_model,
            system=prompts.SYSTEM,
            messages=[
                {
                    "role": "user",
                    "content": prompts.change_request_prompt(
                        current_files_json, spec_json, change_requests
                    ),
                }
            ],
            max_tokens=16384,
        )
        text = response.content[0].text.strip()  # type: ignore[union-attr]

        # Strip markdown fences
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(
                lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
            )

        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return {k: v for k, v in data.items() if isinstance(v, str)}
        except json.JSONDecodeError:
            logger.warning("change_request_parse_failed")
        return {}

    # ------------------------------------------------------------------
    # Local server lifecycle
    # ------------------------------------------------------------------

    def _start_server(
        self, state: PipelineState, app_dir: Path
    ) -> subprocess.Popen:
        """Launch the app in a subprocess on _PREVIEW_PORT."""
        assert state.app_spec is not None
        framework = state.app_spec.backend_framework
        entrypoint = (
            state.development_result.app_entrypoint  # type: ignore[union-attr]
            if state.development_result
            else "backend/main.py"
        )

        cmd = self._build_server_command(framework, entrypoint, app_dir)
        env = {**os.environ, "PYTHONPATH": str(app_dir)}

        logger.info("starting_local_server", cmd=" ".join(cmd), port=_PREVIEW_PORT)
        proc = subprocess.Popen(
            cmd,
            cwd=str(app_dir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        return proc

    def _build_server_command(
        self, framework: str, entrypoint: str, app_dir: Path
    ) -> list[str]:
        """Return the shell command list to start the dev server."""
        # Convert file path like "backend/main.py" → module "backend.main"
        module = entrypoint.replace("/", ".").removesuffix(".py")

        if framework == "flask":
            return [
                sys.executable, "-m", "flask", "run",
                "--host", "127.0.0.1",
                "--port", str(_PREVIEW_PORT),
                "--no-debugger",
            ]
        # FastAPI (default)
        return [
            sys.executable, "-m", "uvicorn",
            f"{module}:app",
            "--host", "127.0.0.1",
            "--port", str(_PREVIEW_PORT),
            "--reload",
        ]

    def _wait_for_server(self) -> bool:
        """Poll until the server responds or the timeout is reached."""
        deadline = time.time() + _SERVER_READY_TIMEOUT
        while time.time() < deadline:
            try:
                resp = httpx.get(_HEALTH_URL, timeout=2)
                if resp.status_code < 500:
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def _stop_server(self, proc: subprocess.Popen) -> None:
        """Gracefully terminate the local server process."""
        if proc.poll() is not None:
            return  # already exited
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        logger.info("local_server_stopped")
