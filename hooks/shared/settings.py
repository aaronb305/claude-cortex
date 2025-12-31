#!/usr/bin/env python3
"""
Settings management for claude-cortex.

Reads configuration from .claude/cortex-settings.json with sensible defaults.
"""

from pathlib import Path
from typing import Any, Optional
from .json_utils import read_json

# Default settings - optimized for token efficiency
DEFAULT_SETTINGS = {
    "session_start": {
        "global_learning_limit": 3,
        "project_learning_limit": 3,
        "global_min_confidence": 0.8,
        "project_min_confidence": 0.7,
        "show_orchestration_guidance": False,  # Only show on first session
        "handoff_max_completed_tasks": 3,
        "handoff_max_pending_tasks": 5,
        "summary_limit": 2,
        "summary_max_length": 300,
        "suggestion_limit": 2,
    },
    "extraction": {
        # Confidence by extraction source
        "user_tagged_confidence": 0.70,  # User explicitly tagged
        "stop_hook_confidence": 0.50,  # Auto-detected by patterns
        "llm_analysis_confidence": 0.40,  # AI extracted from transcript
        "consensus_confidence": 0.85,  # Multiple sources agree
        # Two-pass extraction settings
        "enable_deep_pass": False,  # Run LLM analysis on session end
        "deep_pass_threshold": 3,  # Trigger deep pass if fewer than N learnings
    },
    "privacy": {
        "default_level": "public",
        "allow_private_tag": True,
        "allow_project_tag": True,
    },
}


def get_settings_path(project_dir: Optional[Path] = None) -> Path:
    """Get the path to the settings file.

    Args:
        project_dir: Project directory, or None for global settings.

    Returns:
        Path to cortex-settings.json
    """
    if project_dir:
        return project_dir / ".claude" / "cortex-settings.json"
    return Path.home() / ".claude" / "cortex-settings.json"


def load_settings(project_dir: Optional[Path] = None) -> dict:
    """Load settings with fallback to defaults.

    Merges project settings with global settings with defaults.
    Project settings override global settings override defaults.

    Args:
        project_dir: Project directory, or None for global only.

    Returns:
        Merged settings dictionary.
    """
    settings = DEFAULT_SETTINGS.copy()

    # Load global settings
    global_path = get_settings_path(None)
    if global_path.exists():
        global_settings = read_json(global_path)
        if global_settings:
            settings = _deep_merge(settings, global_settings)

    # Load project settings (override global)
    if project_dir:
        project_path = get_settings_path(project_dir)
        if project_path.exists():
            project_settings = read_json(project_path)
            if project_settings:
                settings = _deep_merge(settings, project_settings)

    return settings


def get_setting(key: str, project_dir: Optional[Path] = None, default: Any = None) -> Any:
    """Get a specific setting by dot-notation key.

    Args:
        key: Setting key like "session_start.global_learning_limit"
        project_dir: Project directory for project-specific settings.
        default: Default value if key not found.

    Returns:
        Setting value or default.
    """
    settings = load_settings(project_dir)

    parts = key.split(".")
    current = settings

    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default

    return current


def _deep_merge(base: dict, override: dict) -> dict:
    """Deep merge two dictionaries.

    Args:
        base: Base dictionary.
        override: Override dictionary (takes precedence).

    Returns:
        Merged dictionary.
    """
    result = base.copy()

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value

    return result


def should_show_orchestration(project_dir: Path) -> bool:
    """Check if orchestration guidance should be shown.

    Shows on first session or if explicitly enabled in settings.

    Args:
        project_dir: Project directory.

    Returns:
        True if guidance should be shown.
    """
    settings = load_settings(project_dir)

    # Check if explicitly enabled in settings
    if settings.get("session_start", {}).get("show_orchestration_guidance", False):
        return True

    # Check if this is the first session (flag file doesn't exist)
    flag_file = project_dir / ".claude" / ".orchestration_shown"
    if not flag_file.exists():
        # Create flag file for next time
        try:
            flag_file.parent.mkdir(parents=True, exist_ok=True)
            flag_file.touch()
        except Exception:
            pass  # Don't fail if we can't create flag
        return True

    return False
