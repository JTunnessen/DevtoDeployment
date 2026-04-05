from __future__ import annotations

import json
import subprocess
from pathlib import Path

from devtodeploy.state import LoadTestResult
from devtodeploy.utils.logging import get_logger

logger = get_logger("loadtest_runner")

# Path to the bundled k6 script template
_K6_SCRIPT = Path(__file__).parent.parent.parent / "loadtests" / "k6_script.js"


class LoadTestRunner:
    def run_k6(
        self,
        base_url: str,
        max_users: int = 10000,
        summary_output: str = "/tmp/k6_summary.json",
    ) -> LoadTestResult:
        """Run a k6 load test using the bundled ramp-up script."""
        script = str(_K6_SCRIPT)
        if not Path(script).exists():
            raise FileNotFoundError(f"k6 script not found at {script}")

        cmd = [
            "k6", "run",
            "--env", f"BASE_URL={base_url}",
            "--env", f"MAX_VUS={max_users}",
            "--summary-export", summary_output,
            script,
        ]
        logger.info("k6_starting", base_url=base_url, max_users=max_users)
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        logger.info("k6_exit_code", code=result.returncode)

        return self._parse_k6_summary(summary_output, max_users, result.returncode)

    def _parse_k6_summary(
        self, summary_path: str, max_users: int, exit_code: int
    ) -> LoadTestResult:
        try:
            with open(summary_path) as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            logger.warning("k6_summary_parse_failed", path=summary_path)
            return LoadTestResult(tool="k6", max_users=max_users, passed=False)

        metrics = data.get("metrics", {})

        p95 = (
            metrics.get("http_req_duration", {})
            .get("values", {})
            .get("p(95)", 0.0)
        )
        avg = (
            metrics.get("http_req_duration", {})
            .get("values", {})
            .get("avg", 0.0)
        )
        error_rate = (
            metrics.get("http_req_failed", {})
            .get("values", {})
            .get("rate", 0.0)
        ) * 100
        rps = (
            metrics.get("http_reqs", {})
            .get("values", {})
            .get("rate", 0.0)
        )

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
