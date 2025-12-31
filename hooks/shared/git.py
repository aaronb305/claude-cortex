#!/usr/bin/env python3
"""
Git utilities for working with repositories.
"""

import subprocess
from pathlib import Path


def get_modified_files(project_dir: Path) -> list[str]:
    """Get list of modified files using git.

    Args:
        project_dir: The project directory.

    Returns:
        List of file paths that have been modified according to git status.
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []

        files = []
        for line in result.stdout.strip().split("\n"):
            if line:
                file_path = line[3:].strip()
                if " -> " in file_path:
                    file_path = file_path.split(" -> ")[1]
                files.append(file_path)
        return files
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        return []


__all__ = ["get_modified_files"]
