from __future__ import annotations

import os
from pathlib import Path


def app_home() -> Path:
    """
    Returns the base directory for storing user data (projects, tokens).

    Default: ~/.youtube-scheduler
    Override with env var: YTSCHEDULER_HOME
    """
    override = os.environ.get("YTSCHEDULER_HOME")
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / ".youtube-scheduler"


def projects_dir() -> Path:
    return app_home() / "projects"


def ensure_dirs() -> None:
    projects_dir().mkdir(parents=True, exist_ok=True)


