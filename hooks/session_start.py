#!/usr/bin/env python3
"""
SessionStart hook for continuous-claude-custom.

Injects ledger context into Claude sessions by reading high-confidence
learnings from both global and project ledgers.

Also loads and displays the latest handoff if available.
"""

import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


def get_ledger_path(project_dir: Optional[str], is_global: bool = False) -> Path:
    """Get the path to a ledger directory."""
    if is_global:
        return Path.home() / ".claude" / "ledger"
    elif project_dir:
        return Path(project_dir) / ".claude" / "ledger"
    else:
        return Path.cwd() / ".claude" / "ledger"


def read_json(path: Path) -> dict:
    """Read JSON from a file."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def get_learnings_by_confidence(
    ledger_path: Path,
    min_confidence: float = 0.5,
    limit: int = 15,
) -> list[dict]:
    """Get learnings sorted by confidence."""
    reinforcements_file = ledger_path / "reinforcements.json"
    reinforcements = read_json(reinforcements_file)
    learnings = reinforcements.get("learnings", {})

    results = []
    for learning_id, data in learnings.items():
        if data.get("confidence", 0) >= min_confidence:
            results.append({
                "id": learning_id,
                **data,
            })

    results.sort(key=lambda x: x.get("confidence", 0), reverse=True)
    return results[:limit]


def get_learning_content(ledger_path: Path, learning_id: str) -> Optional[str]:
    """Get the actual content of a learning from blocks."""
    blocks_dir = ledger_path / "blocks"
    if not blocks_dir.exists():
        return None

    for block_file in blocks_dir.glob("*.json"):
        try:
            block = read_json(block_file)
            for learning in block.get("learnings", []):
                if learning.get("id") == learning_id:
                    return learning.get("content")
        except Exception:
            continue

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
        except Exception:
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
            if context.lower() == "no additional context.":
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

    except Exception:
        return None


def format_handoff_context(handoff: dict) -> str:
    """Format a handoff for session context injection.

    Args:
        handoff: The handoff data.

    Returns:
        Formatted context string.
    """
    lines = ["## Previous Session Handoff"]
    lines.append(f"Session: {handoff.get('session_id', 'unknown')}")
    lines.append(f"Timestamp: {handoff.get('timestamp', 'unknown')}")
    lines.append("")

    completed = handoff.get("completed_tasks", [])
    if completed:
        lines.append("### Completed")
        for task in completed:
            lines.append(f"- {task}")
        lines.append("")

    pending = handoff.get("pending_tasks", [])
    if pending:
        lines.append("### Pending Tasks (continue from here)")
        for task in pending:
            lines.append(f"- {task}")
        lines.append("")

    blockers = handoff.get("blockers", [])
    if blockers:
        lines.append("### Blockers to Address")
        for blocker in blockers:
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
        lines.append(context_notes)
        lines.append("")

    return "\n".join(lines)


def detect_project_type(project_dir: Path) -> dict:
    """Detect project type and package manager."""
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


def build_orchestration_guidance() -> str:
    """Build orchestration guidance for the main Claude instance."""
    return """## Orchestration Mode - ACTIVE

You are the **orchestrator** for this session. Your role is to coordinate work by deploying specialized agents in parallel, not to do everything yourself.

### CRITICAL: Deploy Agents and Continue Working

For HIGH complexity tasks (multi-step, research-heavy, parallelizable):
→ You **MUST** deploy agents rather than handling directly
→ Deploy **multiple agents in parallel** when tasks are independent
→ **After agents complete, IMMEDIATELY continue** with next steps
→ Do NOT stop for confirmation after collecting agent results
→ Keep working until the entire plan is complete or you are truly blocked

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
├─ Deploy code-implementer agent → writes the feature
├─ Deploy test-writer agent → writes tests (parallel)
├─ Deploy research-agent → checks patterns (parallel)
└─ Orchestrator collects results and synthesizes
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
    """Build context string from ledgers, handoffs, and project info."""
    lines = []

    # Load and display latest handoff if available
    if project_dir and project_dir.exists():
        handoff = load_latest_handoff(project_dir)
        if handoff:
            handoff_context = format_handoff_context(handoff)
            lines.append(handoff_context)

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

    # Global ledger learnings
    global_ledger = get_ledger_path(None, is_global=True)
    if global_ledger.exists():
        global_learnings = get_learnings_by_confidence(global_ledger, min_confidence=0.6, limit=10)
        if global_learnings:
            lines.append("## Global Knowledge (high confidence)")
            for l in global_learnings:
                content = get_learning_content(global_ledger, l["id"])
                if content:
                    conf = int(l.get("confidence", 0) * 100)
                    cat = l.get("category", "unknown")
                    lines.append(f"- [{cat}] ({conf}%): {content[:200]}")
            lines.append("")

    # Project ledger learnings
    if project_dir:
        project_ledger = get_ledger_path(str(project_dir), is_global=False)
        if project_ledger.exists():
            project_learnings = get_learnings_by_confidence(project_ledger, min_confidence=0.5, limit=10)
            if project_learnings:
                lines.append("## Project Knowledge")
                for l in project_learnings:
                    content = get_learning_content(project_ledger, l["id"])
                    if content:
                        conf = int(l.get("confidence", 0) * 100)
                        cat = l.get("category", "unknown")
                        lines.append(f"- [{cat}] ({conf}%): {content[:200]}")
                lines.append("")

    # Add learning extraction instructions
    if lines:
        lines.append("## Knowledge Capture")
        lines.append("As you work, document insights using these tags:")
        lines.append("- [DISCOVERY] New information about the codebase")
        lines.append("- [DECISION] Architectural choices made")
        lines.append("- [ERROR] Mistakes or gotchas to avoid")
        lines.append("- [PATTERN] Reusable solutions identified")
        lines.append("")

    # Add orchestration guidance
    lines.append(build_orchestration_guidance())

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
