#!/usr/bin/env python3
"""
Path utilities for ledger and cache directories.
"""

from pathlib import Path
from typing import Optional


def get_ledger_path(project_dir: Optional[str], is_global: bool = False) -> Path:
    """Get the path to a ledger directory.

    Args:
        project_dir: The project directory path, or None to use cwd.
        is_global: If True, return the global ledger path (~/.claude/ledger).

    Returns:
        Path to the ledger directory.
    """
    if is_global:
        return Path.home() / ".claude" / "ledger"
    elif project_dir:
        return Path(project_dir) / ".claude" / "ledger"
    else:
        return Path.cwd() / ".claude" / "ledger"


def get_search_db_path(ledger_path: Path) -> Path:
    """Get the path to the search database for a ledger.

    Args:
        ledger_path: Path to the ledger directory.

    Returns:
        Path to the SQLite search database.
    """
    cache_dir = ledger_path.parent / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "search.db"


__all__ = ["get_ledger_path", "get_search_db_path"]
