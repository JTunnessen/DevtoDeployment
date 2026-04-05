from __future__ import annotations

import shutil
from pathlib import Path


def ensure_workspace(workspace_dir: str, pipeline_id: str) -> Path:
    """Create and return the workspace directory for a pipeline run."""
    path = Path(workspace_dir) / pipeline_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "app").mkdir(exist_ok=True)
    (path / "terraform").mkdir(exist_ok=True)
    return path


def write_app_files(
    workspace_dir: str, pipeline_id: str, files: dict[str, str]
) -> Path:
    """Write a dict of {relative_path: content} to the app workspace."""
    app_dir = Path(workspace_dir) / pipeline_id / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    for rel_path, content in files.items():
        dest = app_dir / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
    return app_dir


def read_app_files(workspace_dir: str, pipeline_id: str) -> dict[str, str]:
    """Read all files from the app workspace into a dict."""
    app_dir = Path(workspace_dir) / pipeline_id / "app"
    result: dict[str, str] = {}
    if not app_dir.exists():
        return result
    for file_path in app_dir.rglob("*"):
        if file_path.is_file() and ".git" not in file_path.parts:
            rel = file_path.relative_to(app_dir).as_posix()
            try:
                result[rel] = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                pass  # skip binary files
    return result


def clean_workspace(workspace_dir: str, pipeline_id: str) -> None:
    """Remove a pipeline workspace entirely."""
    path = Path(workspace_dir) / pipeline_id
    if path.exists():
        shutil.rmtree(path)
