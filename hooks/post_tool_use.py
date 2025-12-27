#!/usr/bin/env python3
"""
PostToolUse hook for continuous-claude-custom.

Nudges Claude to continue working when there are remaining tasks.
Activates after TodoWrite, Edit, or Write tool uses to encourage
completion of pending work items.
"""

import json
import sys
from typing import Optional


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

    # Only process relevant tools
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
