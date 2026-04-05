from __future__ import annotations

import json
import subprocess
from pathlib import Path

from devtodeploy.state import ScanFinding, ScanResult
from devtodeploy.utils.logging import get_logger

logger = get_logger("semgrep_runner")

_SEVERITY_MAP = {
    "ERROR": "HIGH",
    "WARNING": "MEDIUM",
    "INFO": "LOW",
}


class SemgrepRunner:
    def run(self, target_dir: str, timeout: int = 300) -> ScanResult:
        """Run semgrep --config=auto on target_dir. Returns a ScanResult."""
        target = Path(target_dir)
        if not target.exists():
            raise FileNotFoundError(f"Semgrep target directory not found: {target_dir}")

        logger.info("semgrep_starting", target=target_dir)
        result = subprocess.run(
            ["semgrep", "--config=auto", "--json", str(target)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.warning("semgrep_json_parse_failed", stdout=result.stdout[:500])
            data = {}

        raw_findings = data.get("results", [])
        findings: list[ScanFinding] = []
        high = medium = low = 0

        for f in raw_findings:
            raw_sev = f.get("extra", {}).get("severity", "INFO")
            sev = _SEVERITY_MAP.get(raw_sev.upper(), "LOW")
            findings.append(
                ScanFinding(
                    rule_id=f.get("check_id", "unknown"),
                    severity=sev,
                    message=f.get("extra", {}).get("message", ""),
                    path=f.get("path", ""),
                    line=f.get("start", {}).get("line", 0),
                )
            )
            if sev == "HIGH":
                high += 1
            elif sev == "MEDIUM":
                medium += 1
            else:
                low += 1

        passed = high == 0
        logger.info(
            "semgrep_complete",
            high=high,
            medium=medium,
            low=low,
            passed=passed,
        )
        return ScanResult(
            tool="semgrep",
            findings=findings,
            high_count=high,
            medium_count=medium,
            low_count=low,
            passed=passed,
        )
