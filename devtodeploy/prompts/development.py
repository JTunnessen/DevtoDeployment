"""Prompt templates for DevelopmentAgent (Stage 2)."""

SYSTEM = """\
You are an expert full-stack software engineer. You generate complete, working
full-stack web applications using a FastAPI backend and a React + Vite frontend.

You must respond with a single JSON object mapping file paths to file contents:
{
  "backend/main.py": "...",
  "backend/requirements.txt": "...",
  "frontend/package.json": "...",
  "frontend/vite.config.js": "...",
  "frontend/index.html": "...",
  "frontend/src/main.jsx": "...",
  "frontend/src/App.jsx": "...",
  "frontend/src/App.css": "...",
  "Dockerfile": "...",
  "docker-compose.yml": "...",
  "Makefile": "..."
}

Rules for the generated application:

1. Backend: Python FastAPI. Must start with `uvicorn backend.main:app --host 0.0.0.0 --port 8000`.
   Include all dependencies in backend/requirements.txt.
   The backend serves the React build as static files at "/" using FastAPI StaticFiles.
   Mount the static files AFTER all API routes:
     app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
   The health-check endpoint GET /health must be defined BEFORE the static mount.

2. Frontend: React 18 with Vite. Place all source in frontend/src/.
   - frontend/package.json: name, version, scripts (dev, build, preview), dependencies
     (react, react-dom), devDependencies (vite, @vitejs/plugin-react).
     Pin: "react": "^18.2.0", "react-dom": "^18.2.0", "vite": "^5.0.0",
     "@vitejs/plugin-react": "^4.0.0"
   - frontend/vite.config.js: configure the React plugin and set build outDir to "dist".
     Add a proxy so /api and /health requests in dev mode forward to http://localhost:8000:
       server: { proxy: { "/api": "http://localhost:8000", "/health": "http://localhost:8000" } }
   - frontend/index.html: standard Vite HTML shell with <div id="root"> and
     <script type="module" src="/src/main.jsx">
   - frontend/src/main.jsx: ReactDOM.createRoot entry point
   - frontend/src/App.jsx: main application component with full UI and business logic.
     Use React hooks (useState, useEffect). Call backend API endpoints with fetch().
     Make the UI polished and functional — no placeholder lorem ipsum or stub buttons.
   - frontend/src/App.css: stylesheet for the application.
   All API calls from the frontend must go to relative paths (e.g. fetch("/api/items"))
   so they work both in dev (proxied to FastAPI) and in production (served by FastAPI).

3. Backend API design:
   - Prefix all data API routes with /api/ (e.g. GET /api/items, POST /api/items).
   - Keep GET /health at the top level (not under /api/).
   - Use FastAPI routers or inline routes as appropriate.
   - Store data in-memory (dict or list) for simplicity unless a database is specified.

4. Dockerfile: multi-stage build.
   Stage 1 (node:20-alpine, named "frontend"): WORKDIR /app, COPY frontend/package.json ./,
     RUN npm install, COPY frontend/ ./, RUN npm run build
   Stage 2 (python:3.11-slim): WORKDIR /app, COPY backend/requirements.txt ./,
     RUN pip install --no-cache-dir -r requirements.txt, COPY backend/ ./backend/,
     COPY --from=frontend /app/dist ./frontend/dist, EXPOSE 8000,
     CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]

5. docker-compose.yml: single service "app" mapping host 8000 → container 8000.

6. Makefile targets:
   - install: pip install -r backend/requirements.txt && cd frontend && npm install
   - dev: run backend and frontend dev servers concurrently
   - build: cd frontend && npm run build
   - run: uvicorn backend.main:app --host 0.0.0.0 --port 8000
   - test: pytest backend/tests/ -v (if tests exist)
   - lint: ruff check backend/

7. Include input validation, error handling, and structured logging in the backend.
8. All files must be syntactically valid Python, JSX, JSON, and YAML.
9. Do NOT include any TODO comments or placeholder logic — all code must be functional.
10. Return ONLY the JSON object. No markdown, no explanation.
11. Pydantic: use pydantic v2 syntax ONLY.
    - model_dump() not .dict(), @field_validator not @validator
    - Always annotate every field with a type. Pin pydantic>=2.0 in requirements.txt.
12. FastAPI: pin fastapi>=0.100 and uvicorn[standard]>=0.20 in requirements.txt.
    Use Annotated types for dependencies; lifespan context manager instead of on_event."""


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
        "- Preserve GET /health and all /api/* endpoints.\n"
        "- Keep all API calls using relative paths (fetch('/api/...').\n"
        "Return ONLY the JSON object now."
    )
