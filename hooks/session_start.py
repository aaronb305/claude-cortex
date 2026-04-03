#!/usr/bin/env python3
"""
SessionStart hook for claude-cortex (v2).

Slim injection (~180 tokens): pending work + top learnings + MCP pointer.
Summaries, suggestions, orchestration guidance moved to MCP tools / CLAUDE.md.
"""

import json
import sys
from pathlib import Path
from typing import Optional

# Ensure shared module is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).parent))

from shared import (
    get_ledger_path,
    load_latest_handoff,
    get_learnings_by_confidence,
    get_learning_content,
    load_settings,
)


def format_slim_handoff(handoff: dict) -> str:
    """Format handoff as compact pending work summary.

    Only includes pending tasks (max 3) and blockers (max 2).
    """
    lines = ["## Pending Work"]

    pending = handoff.get("pending_tasks", [])
    if pending:
        for task in pending[:3]:
            lines.append(f"- {task}")
    else:
        lines.append("- (no pending tasks)")

    blockers = handoff.get("blockers", [])
    for blocker in blockers[:2]:
        lines.append(f"[Blocker: {blocker}]")

    session_id = handoff.get("session_id", "unknown")[:8]
    timestamp = handoff.get("timestamp", "unknown")[:10]
    lines.append(f"(Session {session_id}, {timestamp})")
    lines.append("")

    return "\n".join(lines)


def get_top_learnings(project_dir: Optional[Path], settings: dict) -> list[tuple[str, int, str]]:
    """Get top learnings merged from global + project ledgers, sorted by confidence.

    Returns:
        List of (category, confidence_pct, content_snippet) tuples, max 3.
    """
    ss = settings.get("session_start", {})
    global_min_conf = ss.get("global_min_confidence", 0.8)
    project_min_conf = ss.get("project_min_confidence", 0.7)

    candidates = []  # (confidence, category, content)

    # Global learnings
    global_ledger = get_ledger_path(None, is_global=True)
    if global_ledger.exists():
        for l in get_learnings_by_confidence(global_ledger, min_confidence=global_min_conf, limit=5):
            content = get_learning_content(global_ledger, l["id"])
            if content:
                candidates.append((
                    l.get("confidence", 0),
                    l.get("category", "unknown"),
                    content,
                ))

    # Project learnings
    if project_dir:
        project_ledger = get_ledger_path(str(project_dir), is_global=False)
        if project_ledger.exists():
            for l in get_learnings_by_confidence(project_ledger, min_confidence=project_min_conf, limit=5):
                content = get_learning_content(project_ledger, l["id"])
                if content:
                    candidates.append((
                        l.get("confidence", 0),
                        l.get("category", "unknown"),
                        content,
                    ))

    # Sort by confidence descending, take top 3
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [(cat, int(conf * 100), text[:80]) for conf, cat, text in candidates[:3]]


def build_context(project_dir: Optional[Path]) -> str:
    """Build slim context string (~180 tokens).

    Includes only: pending work, top learnings, MCP tool pointer.
    """
    settings = load_settings(project_dir)
    lines = []

    # Slim handoff: pending tasks + blockers only
    if project_dir and project_dir.exists():
        handoff = load_latest_handoff(project_dir)
        if handoff:
            lines.append(format_slim_handoff(handoff))

    # Top 3 learnings merged from global + project
    learnings = get_top_learnings(project_dir, settings)
    if learnings:
        lines.append("## Key Knowledge")
        for cat, conf, content in learnings:
            lines.append(f"- [{cat}] ({conf}%): {content}")
        lines.append("")

    # MCP tool pointer
    if lines:
        lines.append("*Use `search_learnings` or `get_handoff` MCP tools for deeper context.*")
        lines.append("")

    return "\n".join(lines) if lines else ""


def main():
    """Main hook entry point."""
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    cwd = input_data.get("cwd", "")
    project_dir = Path(cwd) if cwd else Path.cwd()

    context = build_context(project_dir)

    if context:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": f"# Prior Knowledge from Ledger\n\n{context}"
            }
        }
        print(json.dumps(output))

    sys.exit(0)


if __name__ == "__main__":
    main()
