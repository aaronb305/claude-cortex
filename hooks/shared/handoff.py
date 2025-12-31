#!/usr/bin/env python3
"""
Handoff management: save, load, and parse handoffs.
"""

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .json_utils import write_json


def save_handoff(
    project_dir: Path,
    session_id: str,
    completed_tasks: list[str],
    pending_tasks: list[str],
    blockers: list[str],
    modified_files: list[str],
    context_notes: str = "",
) -> Optional[Path]:
    """Save a handoff to disk.

    Creates a markdown file with session state information including
    completed tasks, pending tasks, blockers, modified files, and context.

    Args:
        project_dir: The project directory.
        session_id: The session identifier.
        completed_tasks: List of completed tasks.
        pending_tasks: List of pending tasks.
        blockers: List of blockers.
        modified_files: List of modified files.
        context_notes: Additional context notes.

    Returns:
        Path to the saved handoff file, or None if failed.
    """
    try:
        handoffs_dir = project_dir / ".claude" / "handoffs" / session_id
        handoffs_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc)
        timestamp_str = timestamp.strftime("%Y%m%d-%H%M%S")
        filename = f"handoff-{timestamp_str}.md"
        file_path = handoffs_dir / filename

        # Build markdown content
        lines = [
            "---",
            f"session_id: {session_id}",
            f"timestamp: {timestamp.isoformat()}",
            "---",
            "",
            "## Completed",
        ]
        if completed_tasks:
            for task in completed_tasks:
                lines.append(f"- {task}")
        else:
            lines.append("- None")
        lines.append("")

        lines.append("## Pending")
        if pending_tasks:
            for task in pending_tasks:
                lines.append(f"- {task}")
        else:
            lines.append("- None")
        lines.append("")

        lines.append("## Modified Files")
        if modified_files:
            for fp in modified_files:
                lines.append(f"- {fp}")
        else:
            lines.append("- None")
        lines.append("")

        lines.append("## Blockers")
        if blockers:
            for blocker in blockers:
                lines.append(f"- {blocker}")
        else:
            lines.append("- None")
        lines.append("")

        lines.append("## Context")
        lines.append(context_notes if context_notes else "No additional context.")
        lines.append("")

        content = "\n".join(lines)
        file_path.write_text(content, encoding="utf-8")

        return file_path
    except Exception as e:
        print(f"[continuous-claude] Warning: Failed to save handoff: {e}", file=sys.stderr)
        return None


def load_latest_handoff(project_dir: Path) -> Optional[dict]:
    """Load the most recent handoff for display.

    Args:
        project_dir: The project directory.

    Returns:
        Handoff data as a dict, or None if not found.
    """
    handoffs_dir = project_dir / ".claude" / "handoffs"
    if not handoffs_dir.exists():
        return None

    # Find all handoff files across all sessions
    handoff_files = list(handoffs_dir.glob("*/handoff-*.md"))
    if not handoff_files:
        return None

    # Sort by filename (contains timestamp) to get most recent
    handoff_files.sort(key=lambda p: p.name, reverse=True)

    # Try to parse the most recent handoff
    for handoff_file in handoff_files:
        try:
            content = handoff_file.read_text(encoding="utf-8")
            handoff = parse_handoff_markdown(content)
            if handoff:
                return handoff
        except Exception as e:
            print(f"[continuous-claude] Warning: Failed to parse handoff {handoff_file}: {e}", file=sys.stderr)
            continue

    return None


def parse_handoff_markdown(content: str) -> Optional[dict]:
    """Parse a handoff from markdown format.

    Args:
        content: The markdown content to parse.

    Returns:
        Handoff data as a dict, or None if parsing fails.
    """
    if not content or not content.strip():
        return None

    try:
        # Parse YAML frontmatter
        frontmatter_match = re.match(
            r"^---\s*\n(.*?)\n---\s*\n",
            content,
            re.DOTALL
        )
        if not frontmatter_match:
            return None

        frontmatter = frontmatter_match.group(1)
        body = content[frontmatter_match.end():]

        # Extract session_id and timestamp from frontmatter
        session_id_match = re.search(r"session_id:\s*(.+)", frontmatter)
        timestamp_match = re.search(r"timestamp:\s*(.+)", frontmatter)

        if not session_id_match or not timestamp_match:
            return None

        session_id = session_id_match.group(1).strip()
        timestamp_str = timestamp_match.group(1).strip()

        # Parse sections from body
        def parse_list_section(section_name: str) -> list[str]:
            pattern = rf"##\s*{re.escape(section_name)}\s*\n(.*?)(?=\n##|\Z)"
            match = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
            if not match:
                return []
            section_content = match.group(1)
            items = []
            for line in section_content.strip().split("\n"):
                line = line.strip()
                if line.startswith("- "):
                    item = line[2:].strip()
                    if item.lower() != "none":
                        items.append(item)
            return items

        def parse_context_section() -> str:
            pattern = r"##\s*Context\s*\n(.*?)(?=\n##|\Z)"
            match = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
            if not match:
                return ""
            context = match.group(1).strip()
            if context.lower() in ("no additional context.", "no additional context"):
                return ""
            return context

        return {
            "session_id": session_id,
            "timestamp": timestamp_str,
            "completed_tasks": parse_list_section("Completed"),
            "pending_tasks": parse_list_section("Pending"),
            "modified_files": parse_list_section("Modified Files"),
            "blockers": parse_list_section("Blockers"),
            "context_notes": parse_context_section(),
        }

    except Exception as e:
        print(f"[continuous-claude] Warning: Failed to parse handoff markdown: {e}", file=sys.stderr)
        return None


__all__ = [
    "save_handoff",
    "load_latest_handoff",
    "parse_handoff_markdown",
]
