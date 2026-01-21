from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Project
from .paths import ensure_dirs, projects_dir


_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def normalize_project_name(name: str) -> str:
    name = name.strip()
    if not name:
        raise ValueError("Project name cannot be empty.")
    normalized = _SAFE_NAME_RE.sub("-", name).strip("-")
    if not normalized:
        raise ValueError("Project name must include at least one letter or number.")
    return normalized


def project_path(project_name: str) -> Path:
    ensure_dirs()
    safe = normalize_project_name(project_name)
    return projects_dir() / f"{safe}.json"


def list_projects() -> list[str]:
    ensure_dirs()
    items = []
    for p in projects_dir().glob("*.json"):
        items.append(p.stem)
    return sorted(items)


def load_project(project_name: str) -> Project:
    path = project_path(project_name)
    if not path.exists():
        raise FileNotFoundError(f"Project not found: {project_name}")
    data = json.loads(path.read_text(encoding="utf-8"))
    return Project.from_json(data)


def save_project(project: Project) -> Path:
    path = project_path(project.name)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(project.to_json(), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


def create_project(project_name: str) -> Project:
    safe = normalize_project_name(project_name)
    path = project_path(safe)
    if path.exists():
        raise FileExistsError(f"Project already exists: {safe}")
    project = Project(name=safe)
    save_project(project)
    return project


def delete_project(project_name: str) -> None:
    path = project_path(project_name)
    if path.exists():
        path.unlink()


