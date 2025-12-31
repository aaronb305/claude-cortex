#!/usr/bin/env python3
"""
Session learnings tracking utilities.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from .locking import file_lock


def get_session_learnings_path(cwd: str) -> Path:
    """Get the path to the session learnings tracking file.

    Args:
        cwd: Current working directory.

    Returns:
        Path to the session_learnings.json file.
    """
    project_dir = Path(cwd) if cwd else Path.cwd()
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    return claude_dir / "session_learnings.json"


def load_session_learnings(path: Path) -> dict:
    """Load existing session learnings data with file locking.

    Args:
        path: Path to the session_learnings.json file.

    Returns:
        Session learnings data dict with referenced_learnings and last_updated.
    """
    try:
        if path.exists():
            with file_lock(path, exclusive=False):
                with open(path) as f:
                    return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return {"referenced_learnings": [], "last_updated": None}


def save_session_learnings(path: Path, data: dict) -> None:
    """Save session learnings data with file locking.

    Args:
        path: Path to the session_learnings.json file.
        data: Session learnings data to save.
    """
    data["last_updated"] = datetime.now(timezone.utc).isoformat()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(path, exclusive=True):
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
    except IOError:
        pass  # Silently fail if we can't write


__all__ = [
    "get_session_learnings_path",
    "load_session_learnings",
    "save_session_learnings",
]
