#!/usr/bin/env python3
"""
Project type detection utilities.
"""

from pathlib import Path


def detect_project_type(project_dir: Path) -> dict:
    """Detect project type and package manager.

    Args:
        project_dir: The project directory.

    Returns:
        Dictionary with type, package_manager, and commands fields.
    """
    result = {"type": "unknown", "package_manager": None, "commands": {}}

    pyproject = project_dir / "pyproject.toml"
    if pyproject.exists():
        result["type"] = "python"
        result["package_manager"] = "uv"
        result["commands"] = {
            "install": "uv sync",
            "run": "uv run python",
            "test": "uv run pytest",
            "add_dep": "uv add",
        }
        return result

    package_json = project_dir / "package.json"
    if package_json.exists():
        if (project_dir / "bun.lockb").exists():
            result["type"] = "node"
            result["package_manager"] = "bun"
            result["commands"] = {
                "install": "bun install",
                "run": "bun run",
                "test": "bun test",
                "add_dep": "bun add",
            }
        else:
            result["type"] = "node"
            result["package_manager"] = "npm"
            result["commands"] = {
                "install": "npm install",
                "run": "npm run",
                "test": "npm test",
                "add_dep": "npm install",
            }
        return result

    return result


__all__ = ["detect_project_type"]
