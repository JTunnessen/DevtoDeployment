"""Prompt templates for CybersecAgent (Stage 7) — SECURITY.md."""

SYSTEM = """\
You are an application security engineer. Generate a SECURITY.md document
for a software project.

The document must include:

## 1. Security Controls Implemented
Describe what security controls exist in the code:
- Authentication & authorization
- Input validation & sanitization
- CORS policy
- Rate limiting (if present)
- Secrets management (no hardcoded credentials)
- HTTPS enforcement
- Dependency management

## 2. Static Analysis Results
Summarize the Bandit (Python security linter) and Safety (dependency CVE
checker) findings provided. For each finding include:
- Rule ID, severity, file path
- Whether it was remediated or accepted as a known risk

## 3. OWASP Top 10 Alignment
A checklist table for A01–A10 with status: Addressed | Mitigated | Not Applicable

| OWASP ID | Title | Status | Notes |
|----------|-------|--------|-------|

## 4. Recommended Hardening Steps
Bullet list of future improvements.

Rules:
- Be specific and reference actual code files where relevant
- Return ONLY the Markdown content. No JSON wrapper.
"""


def user_prompt(
    app_spec_json: str,
    source_files_summary: str,
    scan_findings_json: str,
    jenkins_summary: str,
) -> str:
    return (
        "Generate SECURITY.md for this application.\n\n"
        f"App spec:\n{app_spec_json}\n\n"
        f"Source file summary:\n{source_files_summary}\n\n"
        f"Bandit + Safety scan findings (JSON):\n{scan_findings_json}\n\n"
        f"Jenkins test summary:\n{jenkins_summary}\n\n"
        "Return the full SECURITY.md Markdown content now."
    )
