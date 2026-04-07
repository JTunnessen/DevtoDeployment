from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

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
_SERVER_READY_TIMEOUT = 60  # seconds
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
        import anthropic
        self.client = anthropic.Anthropic(api_key=config.anthropic_api_key)

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self, state: PipelineState) -> PipelineState:
        assert state.development_result is not None
        assert state.app_spec is not None

        app_dir = Path(self.config.workspace_dir) / state.pipeline_id / "app"

        # Ensure server dependencies are installed before trying to start
        self._ensure_server_deps(state, app_dir)

        console.print()
        console.print(
            Panel(
                "[bold]Local Preview[/bold]\n\n"
                "Your generated application will launch in your browser.\n"
                "Review it, request changes if needed, and type [bold green]no[/] "
                "when you're happy to continue the pipeline.\n\n"
                "[dim]Type 'skip' at any prompt to skip the preview and continue.[/]",
                border_style="cyan",
                title="[bold cyan]INTERACTIVE PREVIEW[/]",
            )
        )

        preview_round = 0
        while True:
            preview_round += 1
            server_proc, stderr_file = self._start_server(state, app_dir)

            try:
                ready = self._wait_for_server(server_proc)

                if not ready:
                    # Show what the server printed to stderr to help diagnose
                    stderr_output = self._read_stderr(stderr_file)
                    console.print(
                        f"\n  [red]Server did not start on "
                        f"http://127.0.0.1:{_PREVIEW_PORT} "
                        f"within {_SERVER_READY_TIMEOUT}s.[/]"
                    )
                    if stderr_output:
                        console.print("\n  [bold]Server error output:[/]")
                        for line in stderr_output.splitlines()[-20:]:
                            console.print(f"  [red dim]{line}[/]")

                    skip = Confirm.ask(
                        "\n  Skip local preview and continue the pipeline?",
                        default=True,
                    )
                    if skip:
                        state.local_preview_completed = True
                        return state
                    # Try again next round (server will be restarted)
                    continue

                console.print(
                    f"\n  [bold cyan]App running at[/] "
                    f"http://127.0.0.1:{_PREVIEW_PORT}\n"
                )
                webbrowser.open(_ROOT_URL)

                wants_changes = Confirm.ask(
                    "\n  Would you like to make any changes or enhancements?",
                    default=False,
                )

                if not wants_changes:
                    console.print(
                        "\n  [green]Great! Continuing to the next pipeline stage…[/]\n"
                    )
                    break

                change_requests = self._collect_change_requests()
                if change_requests == ["skip"]:
                    break

            finally:
                self._stop_server(server_proc)
                self._cleanup_stderr(stderr_file)

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
            "  Type [bold]skip[/] to skip the preview entirely.\n"
        )
        requests: list[str] = []
        idx = 1
        while True:
            entry = Prompt.ask(f"  Change {idx}").strip()
            if entry.lower() == "skip":
                return ["skip"]
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
    # Dependency installation
    # ------------------------------------------------------------------

    def _ensure_server_deps(self, state: PipelineState, app_dir: Path) -> None:
        """Install Python deps and build the React frontend before starting the server."""
        # 1. Python backend dependencies
        for req_candidate in [
            app_dir / "backend" / "requirements.txt",
            app_dir / "requirements.txt",
        ]:
            if req_candidate.exists():
                console.print("  [dim]Installing Python dependencies…[/]")
                subprocess.run(
                    [sys.executable, "-m", "pip", "install", "-r", str(req_candidate), "-q"],
                    capture_output=True,
                )
                break

        # Ensure uvicorn/fastapi are available
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "uvicorn[standard]", "fastapi", "-q"],
            capture_output=True,
        )

        # 2. React/Vite frontend build
        frontend_dir = app_dir / "frontend"
        if (frontend_dir / "package.json").exists():
            self._build_react_frontend(frontend_dir)

    def _build_react_frontend(self, frontend_dir: Path) -> None:
        """Run npm install + npm run build for the React frontend."""
        console.print("  [dim]Installing frontend dependencies (npm install)…[/]")
        result = subprocess.run(
            ["npm", "install"],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            console.print(
                "  [yellow]npm install failed — Node.js may not be installed. "
                "Skipping React build; preview may not render correctly.[/]"
            )
            if result.stderr:
                console.print(f"  [red dim]{result.stderr[-300:]}[/]")
            return

        console.print("  [dim]Building React frontend (npm run build)…[/]")
        result = subprocess.run(
            ["npm", "run", "build"],
            cwd=str(frontend_dir),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            console.print("  [yellow]React build failed — preview may show a blank page.[/]")
            if result.stderr:
                console.print(f"  [red dim]{result.stderr[-500:]}[/]")
        else:
            console.print("  [green]React build complete.[/]")

    # ------------------------------------------------------------------
    # Local server lifecycle
    # ------------------------------------------------------------------

    def _start_server(
        self, state: PipelineState, app_dir: Path
    ) -> tuple[subprocess.Popen, str]:
        """Launch the app in a subprocess on _PREVIEW_PORT.
        Returns (process, stderr_temp_file_path).
        """
        assert state.app_spec is not None
        framework = state.app_spec.backend_framework
        entrypoint = (
            state.development_result.app_entrypoint  # type: ignore[union-attr]
            if state.development_result
            else "backend/main.py"
        )

        cmd = self._build_server_command(framework, entrypoint, app_dir)
        env = {**os.environ, "PYTHONPATH": str(app_dir)}

        # Write stderr to a temp file so we can display it on failure
        stderr_fd, stderr_path = tempfile.mkstemp(suffix=".txt", prefix="devtodeploy_server_")
        os.close(stderr_fd)

        logger.info("starting_local_server", cmd=" ".join(cmd), port=_PREVIEW_PORT)
        proc = subprocess.Popen(
            cmd,
            cwd=str(app_dir),
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=open(stderr_path, "w"),
        )
        return proc, stderr_path

    def _build_server_command(
        self, framework: str, entrypoint: str, app_dir: Path
    ) -> list[str]:
        """Return the shell command list to start the FastAPI server."""
        # Convert "backend/main.py" → "backend.main"
        module = entrypoint.replace("\\", "/").replace("/", ".").removesuffix(".py")
        return [
            sys.executable, "-m", "uvicorn",
            f"{module}:app",
            "--host", "127.0.0.1",
            "--port", str(_PREVIEW_PORT),
            "--reload",
        ]

    def _wait_for_server(self, proc: subprocess.Popen) -> bool:
        """Poll until the server responds, times out, or the process exits early."""
        deadline = time.time() + _SERVER_READY_TIMEOUT
        while time.time() < deadline:
            # Detect immediate crash
            if proc.poll() is not None:
                logger.warning("server_process_exited_early", returncode=proc.returncode)
                return False
            try:
                resp = httpx.get(_HEALTH_URL, timeout=2)
                if resp.status_code < 500:
                    return True
            except Exception:
                pass
            time.sleep(1)
        return False

    def _read_stderr(self, stderr_path: str) -> str:
        try:
            return Path(stderr_path).read_text(encoding="utf-8", errors="replace")
        except Exception:
            return ""

    def _cleanup_stderr(self, stderr_path: str) -> None:
        try:
            Path(stderr_path).unlink(missing_ok=True)
        except Exception:
            pass

    def _stop_server(self, proc: subprocess.Popen) -> None:
        if proc.poll() is not None:
            return
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        logger.info("local_server_stopped")
