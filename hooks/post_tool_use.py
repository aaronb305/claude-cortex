#!/usr/bin/env python3
"""
PostToolUse hook for claude-cortex.

Tracks learning references in tool outputs for outcome suggestion at session end.
Zero token injection — pure silent tracking.
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional

# Ensure shared module is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).parent))

from shared import (
    file_lock,
    get_session_learnings_path,
    load_session_learnings,
    save_session_learnings,
)


# Regex patterns for detecting learning references
# UUID format: 8-4-4-4-12 hex characters (full or prefix)
UUID_PATTERN = re.compile(r'\b([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})\b', re.IGNORECASE)
# Explicit learning reference patterns
LEARNING_REF_PATTERNS = [
    re.compile(r'learning[:\s]+([a-f0-9]{8,})', re.IGNORECASE),
    re.compile(r'from learning[:\s]+([a-f0-9]{8,})', re.IGNORECASE),
    re.compile(r'applying learning[:\s]+([a-f0-9]{8,})', re.IGNORECASE),
    re.compile(r'\[([a-f0-9]{8,})\]', re.IGNORECASE),  # [abc12345] format
]


def extract_learning_ids_from_text(text: str) -> list[str]:
    """Extract potential learning IDs from text content.

    Returns:
        List of potential learning IDs (8-char prefixes or full UUIDs)
    """
    found_ids = set()

    # Check explicit learning reference patterns first
    for pattern in LEARNING_REF_PATTERNS:
        matches = pattern.findall(text)
        for match in matches:
            # Normalize to 8-char prefix
            found_ids.add(match[:8].lower())

    # Check for full UUIDs
    uuid_matches = UUID_PATTERN.findall(text)
    for match in uuid_matches:
        found_ids.add(match[:8].lower())

    return list(found_ids)


def validate_learning_ids(
    potential_ids: list[str],
    cwd: str,
) -> list[str]:
    """Validate that potential IDs actually exist in the ledger.

    Args:
        potential_ids: List of potential 8-char learning ID prefixes
        cwd: Current working directory

    Returns:
        List of validated learning IDs that exist in the ledger
    """
    if not potential_ids:
        return []

    validated = []

    # Check project ledger
    project_dir = Path(cwd) if cwd else Path.cwd()
    project_reinforcements = project_dir / ".claude" / "ledger" / "reinforcements.json"

    # Check global ledger
    global_reinforcements = Path.home() / ".claude" / "ledger" / "reinforcements.json"

    all_learning_ids = set()

    for reinforcements_path in [project_reinforcements, global_reinforcements]:
        if reinforcements_path.exists():
            try:
                # Use shared lock to prevent reading while another process writes
                with file_lock(reinforcements_path, exclusive=False):
                    with open(reinforcements_path) as f:
                        data = json.load(f)
                        for lid in data.get("learnings", {}).keys():
                            all_learning_ids.add(lid[:8].lower())
            except (json.JSONDecodeError, IOError):
                pass

    for pid in potential_ids:
        if pid.lower() in all_learning_ids:
            validated.append(pid.lower())

    return validated


def track_learning_references(
    tool_output: Optional[dict],
    cwd: str,
    session_id: str,
) -> None:
    """Track any learning references in the tool output.

    Args:
        tool_output: The output from the tool (may contain Claude's response)
        cwd: Current working directory
        session_id: Current session ID
    """
    if not tool_output:
        return

    # Extract text content from tool output
    text_content = ""

    # Handle different output formats
    if isinstance(tool_output, dict):
        # Check common fields that might contain learning references
        for field in ["content", "text", "result", "message", "output"]:
            if field in tool_output:
                val = tool_output[field]
                if isinstance(val, str):
                    text_content += val + " "
                elif isinstance(val, list):
                    for item in val:
                        if isinstance(item, dict) and "text" in item:
                            text_content += item["text"] + " "
                        elif isinstance(item, str):
                            text_content += item + " "
    elif isinstance(tool_output, str):
        text_content = tool_output

    if not text_content.strip():
        return

    # Extract and validate learning IDs
    potential_ids = extract_learning_ids_from_text(text_content)
    if not potential_ids:
        return

    validated_ids = validate_learning_ids(potential_ids, cwd)
    if not validated_ids:
        return

    # Save to session learnings file
    path = get_session_learnings_path(cwd)
    data = load_session_learnings(path)

    # Add new references (avoid duplicates)
    existing = set(data.get("referenced_learnings", []))
    for lid in validated_ids:
        existing.add(lid)

    data["referenced_learnings"] = list(existing)
    data["session_id"] = session_id

    save_session_learnings(path, data)


def main():
    """Main hook entry point."""
    try:
        # Read hook input from stdin
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        # No input or invalid JSON - continue silently
        sys.exit(0)

    # Extract hook input fields
    tool_output = input_data.get("tool_output", {})
    tool_input = input_data.get("tool_input", {})
    session_id = input_data.get("session_id", "")
    cwd = input_data.get("cwd", "")

    # Track learning references in all tool outputs (silent, zero injection)
    try:
        track_learning_references(tool_output, cwd, session_id)
        if tool_input:
            track_learning_references(tool_input, cwd, session_id)
    except Exception as e:
        print(f"[claude-cortex] PostToolUse: Learning tracking error: {e}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
