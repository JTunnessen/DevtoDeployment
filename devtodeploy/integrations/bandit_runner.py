from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from devtodeploy.state import ScanFinding, ScanResult
from devtodeploy.utils.logging import get_logger

logger = get_logger("bandit_runner")

_BANDIT_SEVERITY_MAP = {
    "HIGH": "HIGH",
    "MEDIUM": "MEDIUM",
    "LOW": "LOW",
}


def _tool_available(name: str) -> bool:
    return shutil.which(name) is not None


class BanditRunner:
    """
    Runs Bandit (Python security linter) and Safety (dependency CVE checker)
    against generated application code. Both tools install on all platforms
    including Windows.

    Install:
        pip install bandit safety
    """

    def run(self, target_dir: str, requirements_file: str = "") -> ScanResult:
        """
        Scan target_dir with Bandit and (optionally) check requirements_file
        with Safety. Returns a combined ScanResult.
        """
        findings: list[ScanFinding] = []

        # ── Bandit ────────────────────────────────────────────────────────────
        if _tool_available("bandit"):
            findings.extend(self._run_bandit(target_dir))
        else:
            logger.warning(
                "bandit_not_found",
                hint="pip install bandit  to enable Python security scanning.",
            )

        # ── Safety ────────────────────────────────────────────────────────────
        req = requirements_file or self._find_requirements(target_dir)
        if req and _tool_available("safety"):
            findings.extend(self._run_safety(req))
        elif not _tool_available("safety"):
            logger.warning(
                "safety_not_found",
                hint="pip install safety  to enable dependency CVE scanning.",
            )

        high = sum(1 for f in findings if f.severity == "HIGH")
        medium = sum(1 for f in findings if f.severity == "MEDIUM")
        low = sum(1 for f in findings if f.severity == "LOW")
        passed = high == 0

        logger.info(
            "scan_complete",
            tools="bandit+safety",
            high=high,
            medium=medium,
            low=low,
            passed=passed,
        )
        return ScanResult(
            tool="bandit+safety",
            findings=findings,
            high_count=high,
            medium_count=medium,
            low_count=low,
            passed=passed,
        )

    # ── Bandit ────────────────────────────────────────────────────────────────

    def _run_bandit(self, target_dir: str) -> list[ScanFinding]:
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
            out_path = tmp.name

        try:
            result = subprocess.run(
                [
                    "bandit",
                    "-r", target_dir,
                    "-f", "json",
                    "-o", out_path,
                    "--exit-zero",   # don't fail on findings; we parse JSON
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            try:
                data = json.loads(Path(out_path).read_text())
            except (json.JSONDecodeError, FileNotFoundError):
                logger.warning("bandit_json_parse_failed", stderr=result.stderr[:300])
                return []

            findings: list[ScanFinding] = []
            for r in data.get("results", []):
                sev = _BANDIT_SEVERITY_MAP.get(
                    r.get("issue_severity", "LOW").upper(), "LOW"
                )
                findings.append(
                    ScanFinding(
                        rule_id=r.get("test_id", "unknown"),
                        severity=sev,
                        message=r.get("issue_text", ""),
                        path=r.get("filename", ""),
                        line=r.get("line_number", 0),
                    )
                )
            logger.info("bandit_complete", findings=len(findings))
            return findings
        finally:
            Path(out_path).unlink(missing_ok=True)

    # ── Safety ────────────────────────────────────────────────────────────────

    def _run_safety(self, requirements_file: str) -> list[ScanFinding]:
        result = subprocess.run(
            ["safety", "check", "-r", requirements_file, "--json"],
            capture_output=True,
            text=True,
            timeout=60,
        )

        findings: list[ScanFinding] = []
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            logger.warning("safety_json_parse_failed", stdout=result.stdout[:300])
            return []

        # Safety ≥3.x: {"vulnerabilities": [...]}
        vulns = (
            data.get("vulnerabilities", [])
            if isinstance(data, dict)
            else data  # Safety <3.x: list of [pkg, spec, ver, advisory, id]
        )

        for v in vulns:
            if isinstance(v, dict):
                pkg = v.get("package_name", v.get("name", "unknown"))
                advisory = v.get("advisory", v.get("description", ""))
                vid = v.get("vulnerability_id", v.get("CVE", ""))
                raw_sev = v.get("severity", "").upper()
                sev = raw_sev if raw_sev in ("HIGH", "MEDIUM", "LOW") else "MEDIUM"
            else:
                # Old list format: [package, spec, version, advisory, id]
                pkg = v[0] if len(v) > 0 else "unknown"
                advisory = v[3] if len(v) > 3 else ""
                vid = v[4] if len(v) > 4 else ""
                sev = "MEDIUM"

            findings.append(
                ScanFinding(
                    rule_id=f"safety-{vid}" if vid else "safety-vuln",
                    severity=sev,
                    message=f"{pkg}: {advisory}",
                    path=requirements_file,
                    line=0,
                )
            )

        logger.info("safety_complete", findings=len(findings))
        return findings

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_requirements(self, target_dir: str) -> str:
        """Return the first requirements.txt found in target_dir, or empty string."""
        for candidate in [
            Path(target_dir) / "backend" / "requirements.txt",
            Path(target_dir) / "requirements.txt",
        ]:
            if candidate.exists():
                return str(candidate)
        return ""
