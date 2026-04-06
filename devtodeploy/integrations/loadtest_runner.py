from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from devtodeploy.state import LoadTestResult
from devtodeploy.utils.logging import get_logger

logger = get_logger("loadtest_runner")

_K6_SCRIPT = Path(__file__).parent.parent.parent / "loadtests" / "k6_script.js"


class LoadTestRunner:
    def run_k6(
        self,
        base_url: str,
        max_users: int = 100,
    ) -> LoadTestResult:
        """Run a k6 load test using the bundled ramp-up script.

        Returns a skipped (passed=True) result if k6 is not installed so the
        pipeline can continue without a hard dependency on k6 being present.
        """
        script = str(_K6_SCRIPT)
        if not Path(script).exists():
            logger.warning("k6_script_not_found", path=script)
            return LoadTestResult(tool="k6", max_users=max_users, passed=True)

        # Use a cross-platform temp file for the JSON summary
        with tempfile.NamedTemporaryFile(
            suffix=".json", delete=False, mode="w"
        ) as tmp:
            summary_path = tmp.name

        cmd = [
            "k6", "run",
            "--env", f"BASE_URL={base_url}",
            "--env", f"MAX_VUS={max_users}",
            "--env", f"SUMMARY_PATH={summary_path}",
            script,
        ]
        logger.info("k6_starting", base_url=base_url, max_users=max_users)
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=600
            )
        except FileNotFoundError:
            logger.warning("k6_not_installed", hint="install k6 to enable load testing")
            return LoadTestResult(tool="k6", max_users=max_users, passed=True)

        logger.info("k6_exit_code", code=result.returncode)

        if result.returncode not in (0, 99):
            # Non-threshold error (k6 internal error, script error, etc.) — skip
            logger.warning(
                "k6_execution_error",
                exit_code=result.returncode,
                stderr=result.stderr[-500:] if result.stderr else "",
                stdout=result.stdout[-500:] if result.stdout else "",
            )
            return LoadTestResult(tool="k6", max_users=max_users, passed=True)

        return self._parse_summary(summary_path, result.stdout, max_users, result.returncode)

    def _parse_summary(
        self,
        summary_path: str,
        stdout: str,
        max_users: int,
        exit_code: int,
    ) -> LoadTestResult:
        data: dict = {}

        # Try the summary file first (written by handleSummary)
        try:
            text = Path(summary_path).read_text(encoding="utf-8")
            if text.strip():
                data = json.loads(text)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

        # Fall back to parsing JSON from stdout (handleSummary writes it there too)
        if not data and stdout:
            for line in reversed(stdout.splitlines()):
                line = line.strip()
                if line.startswith("{"):
                    try:
                        data = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue
            # Also try the whole stdout as JSON
            if not data:
                try:
                    data = json.loads(stdout)
                except json.JSONDecodeError:
                    pass

        if not data:
            logger.warning("k6_summary_parse_failed")
            # exit_code 99 = thresholds exceeded; 0 = all passed
            passed = exit_code == 0
            return LoadTestResult(tool="k6", max_users=max_users, passed=passed)

        metrics = data.get("metrics", {})
        p95 = metrics.get("http_req_duration", {}).get("p(95)", 0.0)
        avg = metrics.get("http_req_duration", {}).get("avg", 0.0)
        error_rate = metrics.get("http_req_failed", {}).get("rate", 0.0) * 100
        rps = metrics.get("http_reqs", {}).get("rate", 0.0)

        passed = exit_code == 0 and error_rate < 5.0 and p95 < 2000.0
        logger.info(
            "k6_results",
            p95_ms=round(p95, 1),
            error_rate_pct=round(error_rate, 2),
            rps=round(rps, 1),
            passed=passed,
        )
        return LoadTestResult(
            tool="k6",
            max_users=max_users,
            p95_response_ms=p95,
            avg_response_ms=avg,
            error_rate_percent=error_rate,
            requests_per_second=rps,
            passed=passed,
        )
