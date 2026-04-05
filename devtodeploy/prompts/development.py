"""Prompt templates for DevelopmentAgent (Stage 2)."""

SYSTEM = """\
You are an expert full-stack software engineer. You generate complete, working
full-stack web applications.

You must respond with a single JSON object mapping file paths to file contents:
{
  "backend/main.py": "...",
  "backend/requirements.txt": "...",
  "frontend/index.html": "...",
  "Dockerfile": "...",
  "docker-compose.yml": "...",
  "Makefile": "..."
}

Rules for the generated application:
1. Backend: Python (FastAPI or Flask as specified). Must start with `uvicorn backend.main:app`
   (FastAPI) or `flask run` (Flask). Include all dependencies in backend/requirements.txt.
2. Frontend: Vanilla HTML/JS served by the backend at the root path ("/"). For FastAPI
   use StaticFiles; for Flask use send_from_directory. Keep it in frontend/.
3. Dockerfile: multi-stage build, COPY both backend/ and frontend/, EXPOSE 8000.
4. docker-compose.yml: single service called "app" mapping host 8000→container 8000.
5. Makefile: targets — install, run, test, lint.
6. Include at least basic input validation, error handling, and structured logging.
7. All files must be syntactically valid Python, HTML, JS, and YAML.
8. Include a health-check endpoint GET /health returning {"status": "ok"}.
9. Do NOT include any TODO comments or placeholder logic — all code must be functional.
10. Return ONLY the JSON object. No markdown, no explanation.
"""


def initial_prompt(app_spec_json: str) -> str:
    return (
        "Generate the complete full-stack application for this specification:\n\n"
        f"{app_spec_json}\n\n"
        "Return the JSON file map now."
    )


def iteration_prompt(app_spec_json: str, issues: list[str], iteration: int) -> str:
    issues_text = "\n".join(f"- {i}" for i in issues)
    return (
        f"Iteration {iteration}: Fix ALL of the following issues from the previous "
        f"version. Regenerate the COMPLETE file map with all fixes applied.\n\n"
        f"Application spec:\n{app_spec_json}\n\n"
        f"Issues to fix:\n{issues_text}\n\n"
        "Return the complete corrected JSON file map now."
    )


def change_request_prompt(
    current_files_json: str,
    app_spec_json: str,
    change_requests: list[str],
) -> str:
    """Prompt to apply user-requested changes/enhancements during local preview."""
    requests_text = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(change_requests))
    return (
        "The application creator has reviewed the running application and requested "
        "the following changes or enhancements. Apply ALL of them and return the "
        "COMPLETE updated file map.\n\n"
        f"Original application spec:\n{app_spec_json}\n\n"
        f"Current source files:\n{current_files_json}\n\n"
        f"Requested changes:\n{requests_text}\n\n"
        "Rules:\n"
        "- Return the FULL file map — include every file, even unchanged ones.\n"
        "- Implement each change request completely; no placeholders or TODOs.\n"
        "- Preserve the health-check endpoint GET /health.\n"
        "Return ONLY the JSON object now."
    )
