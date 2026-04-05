from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from devtodeploy.utils.logging import get_logger

logger = get_logger("terraform_runner")


class TerraformRunner:
    def __init__(self, working_dir: str) -> None:
        self.working_dir = Path(working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        cmd = ["terraform", *args]
        logger.info("terraform_run", cmd=" ".join(cmd), cwd=str(self.working_dir))
        result = subprocess.run(
            cmd,
            cwd=str(self.working_dir),
            capture_output=False,  # let output flow to terminal
            text=True,
            timeout=600,
        )
        if check and result.returncode != 0:
            raise RuntimeError(
                f"terraform {args[0]} failed (exit {result.returncode})"
            )
        return result

    def init(self) -> None:
        self._run("init", "-input=false")

    def apply(self, variables: dict[str, str]) -> None:
        var_args: list[str] = []
        for k, v in variables.items():
            var_args += ["-var", f"{k}={v}"]
        self._run("apply", "-auto-approve", "-input=false", *var_args)

    def destroy(self, variables: dict[str, str]) -> None:
        var_args: list[str] = []
        for k, v in variables.items():
            var_args += ["-var", f"{k}={v}"]
        self._run("destroy", "-auto-approve", "-input=false", *var_args)

    def output(self) -> dict[str, str]:
        """Return terraform outputs as a flat dict of {key: value}."""
        result = subprocess.run(
            ["terraform", "output", "-json"],
            cwd=str(self.working_dir),
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return {}
        try:
            raw: dict[str, Any] = json.loads(result.stdout)
            return {k: str(v.get("value", "")) for k, v in raw.items()}
        except json.JSONDecodeError:
            return {}
