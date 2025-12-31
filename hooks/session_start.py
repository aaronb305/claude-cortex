#!/usr/bin/env python3
"""
SessionStart hook for claude-cortex.

Injects ledger context into Claude sessions by reading high-confidence
learnings from both global and project ledgers.

Also loads and displays the latest handoff and recent summaries if available.
"""

import json
import sys
from pathlib import Path
from typing import Optional

# Ensure shared module is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).parent))

# Import shared utilities
from shared import (
    get_ledger_path,
    read_json,
    load_latest_handoff,
    get_learnings_by_confidence,
    get_learning_content,
    detect_project_type,
    load_settings,
    should_show_orchestration,
)


def format_handoff_context(handoff: dict, settings: dict) -> str:
    """Format a handoff for session context injection.

    Args:
        handoff: The handoff data.
        settings: Settings dictionary with limits.

    Returns:
        Formatted context string.
    """
    ss = settings.get("session_start", {})
    max_completed = ss.get("handoff_max_completed_tasks", 3)
    max_pending = ss.get("handoff_max_pending_tasks", 5)

    lines = ["## Previous Session Handoff"]
    lines.append(f"Session: {handoff.get('session_id', 'unknown')}")
    lines.append(f"Timestamp: {handoff.get('timestamp', 'unknown')}")
    lines.append("")

    completed = handoff.get("completed_tasks", [])
    if completed:
        lines.append("### Completed")
        for task in completed[:max_completed]:
            lines.append(f"- {task}")
        if len(completed) > max_completed:
            lines.append(f"- ...+{len(completed) - max_completed} more")
        lines.append("")

    pending = handoff.get("pending_tasks", [])
    if pending:
        lines.append("### Pending Tasks (continue from here)")
        for task in pending[:max_pending]:
            lines.append(f"- {task}")
        if len(pending) > max_pending:
            lines.append(f"- ...+{len(pending) - max_pending} more")
        lines.append("")

    blockers = handoff.get("blockers", [])
    if blockers:
        lines.append("### Blockers to Address")
        for blocker in blockers[:3]:  # Limit blockers too
            lines.append(f"- {blocker}")
        lines.append("")

    modified = handoff.get("modified_files", [])
    if modified:
        lines.append("### Recently Modified Files")
        for file_path in modified[:10]:
            lines.append(f"- {file_path}")
        lines.append("")

    context_notes = handoff.get("context_notes", "")
    if context_notes:
        lines.append("### Context Notes")
        # Truncate long notes
        if len(context_notes) > 200:
            lines.append(context_notes[:200] + "...")
        else:
            lines.append(context_notes)
        lines.append("")

    return "\n".join(lines)


def load_recent_summaries(project_dir: Path, limit: int = 3) -> list[dict]:
    """Load recent summaries for context injection.

    Args:
        project_dir: The project directory.
        limit: Maximum number of summaries to load.

    Returns:
        List of summary data dictionaries.
    """
    summaries_dir = project_dir / ".claude" / "summaries"
    if not summaries_dir.exists():
        return []

    # Find all summary files across all sessions
    summary_files = list(summaries_dir.glob("*/summary-*.json"))
    if not summary_files:
        return []

    # Sort by filename (contains timestamp) to get most recent
    summary_files.sort(key=lambda p: p.name, reverse=True)

    results = []
    for summary_file in summary_files[:limit]:
        try:
            data = read_json(summary_file)
            if data:
                results.append(data)
        except Exception:
            continue

    return results


def format_summaries_context(summaries: list[dict], max_length: int = 300) -> str:
    """Format summaries for session context injection.

    Args:
        summaries: List of summary data dictionaries.
        max_length: Maximum length for summary text truncation.

    Returns:
        Formatted context string.
    """
    if not summaries:
        return ""

    lines = ["## Recent Session Summaries"]
    lines.append("")

    for summary in summaries:
        session_id = summary.get("session_id", "unknown")
        timestamp = summary.get("timestamp", "unknown")
        summary_text = summary.get("summary_text", "")
        key_decisions = summary.get("key_decisions", [])
        files_discussed = summary.get("files_discussed", [])

        lines.append(f"### Session {session_id[:8]}")
        lines.append(f"*{timestamp[:19]}*")
        lines.append("")

        if summary_text:
            # Truncate if too long (use configurable max_length)
            if len(summary_text) > max_length:
                lines.append(summary_text[:max_length] + "...")
            else:
                lines.append(summary_text)
            lines.append("")

        if key_decisions:
            lines.append("**Key Decisions:**")
            for decision in key_decisions[:3]:  # Reduced from 5 to 3
                lines.append(f"- {decision}")
            lines.append("")

        if files_discussed:
            lines.append("**Files Involved:**")
            for file_path in files_discussed[:5]:  # Reduced from 10 to 5
                lines.append(f"- {file_path}")
            lines.append("")

    return "\n".join(lines)


def get_cross_project_suggestions(project_dir: Path, limit: int = 3) -> str:
    """Get relevant suggestions from global ledger for the current project.

    Uses the LearningRecommender to find learnings that match the
    current project's type and tech stack.

    Args:
        project_dir: The project directory to analyze.
        limit: Maximum number of suggestions.

    Returns:
        Formatted string with suggestions, or empty string if none.
    """
    try:
        # Import here to avoid circular dependencies
        src_path = Path(__file__).parent.parent / "src"
        if str(src_path) not in sys.path:
            sys.path.insert(0, str(src_path))

        from claude_cortex.suggestions import LearningRecommender
        from claude_cortex.ledger import Ledger

        global_ledger_path = Path.home() / ".claude" / "ledger"
        if not global_ledger_path.exists():
            return ""

        global_ledger = Ledger(global_ledger_path, is_global=True)
        recommender = LearningRecommender(global_ledger)

        # Get top suggestions
        suggestions = recommender.get_suggestions(
            project_dir,
            limit=limit,
            min_confidence=0.5,
        )

        if not suggestions:
            return ""

        lines = ["## Suggested from Global Knowledge"]
        lines.append("")

        for i, suggestion in enumerate(suggestions, 1):
            learning = suggestion.learning
            summary = suggestion.format_summary(max_length=150)
            category = learning.category.value
            confidence = int(learning.confidence * 100)
            relevance = int(suggestion.relevance_score * 100)

            lines.append(f"{i}. [{category}] ({confidence}% conf, {relevance}% match): {summary}")

            # Show match reasons briefly
            if suggestion.match_reasons:
                reasons = ", ".join(suggestion.match_reasons[:2])
                lines.append(f"   *Matched: {reasons}*")

        lines.append("")
        lines.append("*Use `cclaude suggest --apply <id>` to import to project ledger*")
        lines.append("")

        return "\n".join(lines)

    except Exception as e:
        # Don't fail hook if suggestion system has issues, but log the error
        print(f"[claude-cortex] SessionStart: Suggestion system error: {e}", file=sys.stderr)
        return ""


def build_orchestration_guidance() -> str:
    """Build orchestration guidance for the main Claude instance."""
    return """## Orchestration Mode - ACTIVE

You are the **orchestrator** for this session. Your role is to coordinate work by deploying specialized agents in parallel, not to do everything yourself.

### CRITICAL: Deploy Agents and Continue Working

For HIGH complexity tasks (multi-step, research-heavy, parallelizable):
-> You **MUST** deploy agents rather than handling directly
-> Deploy **multiple agents in parallel** when tasks are independent
-> **After agents complete, IMMEDIATELY continue** with next steps
-> Do NOT stop for confirmation after collecting agent results
-> Keep working until the entire plan is complete or you are truly blocked

### Task Complexity Assessment
| Complexity | Indicators | Action |
|------------|------------|--------|
| LOW | Single file, quick lookup, direct query | Use SKILL directly |
| MEDIUM | 2-3 steps, known pattern, focused scope | Consider SKILL or AGENT |
| HIGH | Multi-step, research needed, parallelizable | **DEPLOY AGENT(S)** |

### Parallel Execution Pattern
When you identify independent subtasks, deploy multiple agents simultaneously:
```
Example: "Implement feature X with tests"
|- Deploy code-implementer agent -> writes the feature
|- Deploy test-writer agent -> writes tests (parallel)
|- Deploy research-agent -> checks patterns (parallel)
|- Orchestrator collects results and synthesizes
```

### Available Specialized Agents
**Execution agents** (deploy for focused work):
- `code-implementer` - Writes/modifies code for specific tasks
- `test-writer` - Creates tests for implementations
- `research-agent` - Investigates APIs, libraries, patterns
- `refactorer` - Handles code refactoring tasks
- `bug-investigator` - Debugs and traces issues
- `doc-writer` - Writes/updates documentation

**Coordination agents** (deploy for workflows):
- `continuous-runner` - Coordinates multi-iteration sessions
- `knowledge-retriever` - Deep search and analysis of learnings
- `session-continuity` - Full session restoration
- `learning-extractor` - Analyze conversations for insights
- `outcome-tracker` - Record outcomes, adjust confidence

### Skills (quick operations only)
- `ledger-knowledge` - Direct ledger queries
- `learning-capture` - Tag and save learnings
- `handoff-management` - Save/load WIP state
- `search-learnings` - Full-text search

### Continuous Todo Management
- **Always** use TodoWrite when starting multi-step work
- **Immediately** mark tasks complete as you finish them
- **Never** batch completions - update in real-time
"""


def build_context(project_dir: Optional[Path]) -> str:
    """Build context string from ledgers, handoffs, summaries, and project info.

    Uses settings from cortex-settings.json for limits and thresholds.
    """
    # Load settings
    settings = load_settings(project_dir)
    ss = settings.get("session_start", {})

    # Get configurable limits
    global_limit = ss.get("global_learning_limit", 3)
    project_limit = ss.get("project_learning_limit", 3)
    global_min_conf = ss.get("global_min_confidence", 0.8)
    project_min_conf = ss.get("project_min_confidence", 0.7)
    summary_limit = ss.get("summary_limit", 2)
    summary_max_len = ss.get("summary_max_length", 300)
    suggestion_limit = ss.get("suggestion_limit", 2)

    lines = []

    # Load and display latest handoff if available
    if project_dir and project_dir.exists():
        handoff = load_latest_handoff(project_dir)
        if handoff:
            handoff_context = format_handoff_context(handoff, settings)
            lines.append(handoff_context)

    # Load and display recent summaries if available
    if project_dir and project_dir.exists():
        summaries = load_recent_summaries(project_dir, limit=summary_limit)
        if summaries:
            summaries_context = format_summaries_context(summaries, max_length=summary_max_len)
            lines.append(summaries_context)

    # Project environment context
    if project_dir and project_dir.exists():
        project_info = detect_project_type(project_dir)
        if project_info["type"] != "unknown":
            lines.append("## Project Environment")
            lines.append(f"- Type: {project_info['type']}")
            lines.append(f"- Package manager: {project_info['package_manager']}")
            for name, cmd in project_info["commands"].items():
                lines.append(f"- {name}: `{cmd}`")
            lines.append("")

    # Global ledger learnings (reduced limits, higher threshold)
    global_ledger = get_ledger_path(None, is_global=True)
    if global_ledger.exists():
        global_learnings = get_learnings_by_confidence(
            global_ledger, min_confidence=global_min_conf, limit=global_limit
        )
        if global_learnings:
            lines.append("## Global Knowledge (high confidence)")
            for l in global_learnings:
                content = get_learning_content(global_ledger, l["id"])
                if content:
                    conf = int(l.get("confidence", 0) * 100)
                    cat = l.get("category", "unknown")
                    # Truncate to 150 chars for token efficiency
                    lines.append(f"- [{cat}] ({conf}%): {content[:150]}")
            lines.append("")

    # Project ledger learnings (reduced limits)
    if project_dir:
        project_ledger = get_ledger_path(str(project_dir), is_global=False)
        if project_ledger.exists():
            project_learnings = get_learnings_by_confidence(
                project_ledger, min_confidence=project_min_conf, limit=project_limit
            )
            if project_learnings:
                lines.append("## Project Knowledge")
                for l in project_learnings:
                    content = get_learning_content(project_ledger, l["id"])
                    if content:
                        conf = int(l.get("confidence", 0) * 100)
                        cat = l.get("category", "unknown")
                        lines.append(f"- [{cat}] ({conf}%): {content[:150]}")
                lines.append("")

    # Cross-project suggestions from global ledger (reduced limit)
    if project_dir and project_dir.exists():
        suggestions = get_cross_project_suggestions(project_dir, limit=suggestion_limit)
        if suggestions:
            lines.append(suggestions)

    # Add learning extraction instructions (condensed)
    if lines:
        lines.append("## Knowledge Capture")
        lines.append("As you work, document insights using these tags:")
        lines.append("- [DISCOVERY] New information about the codebase")
        lines.append("- [DECISION] Architectural choices made")
        lines.append("- [ERROR] Mistakes or gotchas to avoid")
        lines.append("- [PATTERN] Reusable solutions identified")
        lines.append("")

    # Add orchestration guidance ONLY if should be shown
    if project_dir and should_show_orchestration(project_dir):
        lines.append(build_orchestration_guidance())
    elif lines:
        # Add brief reminder instead of full guidance
        lines.append("*Use `search_learnings` MCP tool or `/search-learnings` skill for deeper context.*")
        lines.append("")

    return "\n".join(lines) if lines else ""


def main():
    """Main hook entry point."""
    try:
        # Read hook input from stdin
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        # No input or invalid JSON - continue silently
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    cwd = input_data.get("cwd", "")
    source = input_data.get("source", "startup")

    # Determine project directory
    project_dir = Path(cwd) if cwd else Path.cwd()

    # Build context
    context = build_context(project_dir)

    if context:
        # Output context to be injected into session
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
