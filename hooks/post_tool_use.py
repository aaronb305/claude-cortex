#!/usr/bin/env python3
"""
PostToolUse hook for continuous-claude-custom.

Nudges Claude to continue working when there are remaining tasks.
Activates after TodoWrite, Edit, or Write tool uses to encourage
completion of pending work items.

Also tracks learning references for outcome suggestion at session end.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


# Regex patterns for detecting learning references
# UUID format: 8-4-4-4-12 hex characters (full or prefix)
UUID_PATTERN = re.compile(r'\b([a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})\b', re.IGNORECASE)
# Short ID format: 8 hex characters (common prefix usage)
SHORT_ID_PATTERN = re.compile(r'\b([a-f0-9]{8})\b', re.IGNORECASE)
# Explicit learning reference patterns
LEARNING_REF_PATTERNS = [
    re.compile(r'learning[:\s]+([a-f0-9]{8,})', re.IGNORECASE),
    re.compile(r'from learning[:\s]+([a-f0-9]{8,})', re.IGNORECASE),
    re.compile(r'applying learning[:\s]+([a-f0-9]{8,})', re.IGNORECASE),
    re.compile(r'\[([a-f0-9]{8,})\]', re.IGNORECASE),  # [abc12345] format
]


def get_session_learnings_path(cwd: str) -> Path:
    """Get the path to the session learnings tracking file."""
    project_dir = Path(cwd) if cwd else Path.cwd()
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    return claude_dir / "session_learnings.json"


def load_session_learnings(path: Path) -> dict:
    """Load existing session learnings data."""
    try:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return {"referenced_learnings": [], "last_updated": None}


def save_session_learnings(path: Path, data: dict) -> None:
    """Save session learnings data."""
    data["last_updated"] = datetime.utcnow().isoformat()
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except IOError:
        pass  # Silently fail if we can't write


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


def get_pending_tasks(tool_input: dict) -> list[dict]:
    """Extract pending tasks from TodoWrite tool input."""
    todos = tool_input.get("todos", [])
    return [t for t in todos if t.get("status") == "pending"]


def get_in_progress_tasks(tool_input: dict) -> list[dict]:
    """Extract in-progress tasks from TodoWrite tool input."""
    todos = tool_input.get("todos", [])
    return [t for t in todos if t.get("status") == "in_progress"]


def build_nudge_message(
    tool_name: str,
    tool_input: dict,
    tool_output: Optional[dict],
) -> Optional[str]:
    """Build a nudge message based on the tool used and remaining work."""

    if tool_name == "TodoWrite":
        pending = get_pending_tasks(tool_input)
        in_progress = get_in_progress_tasks(tool_input)

        if pending:
            pending_count = len(pending)
            next_task = pending[0].get("content", "next task")

            if in_progress:
                # There's work in progress, gentle reminder about what's next
                return f"{pending_count} task(s) remaining after current work. Next: {next_task[:50]}"
            else:
                # Nothing in progress, nudge to start the next task
                return f"Continue with {pending_count} pending task(s). Start: {next_task[:50]}"

        # All tasks complete
        return None

    elif tool_name in ("Edit", "Write"):
        # For file operations, provide a general continuation nudge
        # We don't have direct access to the todo list here, but we can
        # encourage checking for more work
        file_path = tool_input.get("file_path", "file")
        if "/" in file_path:
            file_name = file_path.split("/")[-1]
        else:
            file_name = file_path

        return f"Completed changes to {file_name}. Check for remaining tasks."

    return None


def main():
    """Main hook entry point."""
    try:
        # Read hook input from stdin
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        # No input or invalid JSON - continue silently
        sys.exit(0)

    # Extract hook input fields
    tool_name = input_data.get("tool_name", "")
    tool_input = input_data.get("tool_input", {})
    tool_output = input_data.get("tool_output", {})
    session_id = input_data.get("session_id", "")
    cwd = input_data.get("cwd", "")

    # Track learning references in all tool outputs
    # This helps with outcome suggestion at session end
    try:
        track_learning_references(tool_output, cwd, session_id)
        # Also check tool_input for learning references (e.g., in file content being read)
        if tool_input:
            track_learning_references(tool_input, cwd, session_id)
    except Exception:
        pass  # Don't fail the hook if tracking fails

    # Only process nudge messages for relevant tools
    relevant_tools = {"TodoWrite", "Edit", "Write"}
    if tool_name not in relevant_tools:
        sys.exit(0)

    # Build nudge message
    nudge = build_nudge_message(tool_name, tool_input, tool_output)

    if nudge:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "statusMessage": nudge
            }
        }
        print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
