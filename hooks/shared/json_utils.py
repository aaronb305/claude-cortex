#!/usr/bin/env python3
"""
JSON utilities with optional file locking.
"""

import json
from pathlib import Path

from .locking import file_lock


def read_json(path: Path) -> dict:
    """Read JSON from a file (no locking, for read-only access).

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON data, or empty dict on error.
    """
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_json(path: Path, data: dict) -> None:
    """Write JSON to a file (no locking, for simple writes).

    Args:
        path: Path to the JSON file.
        data: Data to serialize and write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def read_json_locked(path: Path) -> dict:
    """Read JSON from a file with shared file lock.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON data, or empty dict on error.
    """
    import sys
    try:
        with file_lock(path, exclusive=False):
            return read_json(path)
    except Exception as e:
        print(f"[continuous-claude] Warning: Failed to read {path}: {e}", file=sys.stderr)
        return {}


def write_json_locked(path: Path, data: dict) -> None:
    """Write JSON to a file with exclusive file lock.

    Args:
        path: Path to the JSON file.
        data: Data to serialize and write.
    """
    with file_lock(path, exclusive=True):
        write_json(path, data)


__all__ = ["read_json", "write_json", "read_json_locked", "write_json_locked"]
