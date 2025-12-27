#!/usr/bin/env python3
"""
PreCompact hook for continuous-claude-custom.

Extracts learnings from the conversation BEFORE compaction happens,
ensuring no learnings are lost when the context gets summarized.

Also saves a handoff to capture work-in-progress state.
"""

import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4


class LearningCategory:
    DISCOVERY = "discovery"
    DECISION = "decision"
    ERROR = "error"
    PATTERN = "pattern"


def get_ledger_path(project_dir: Optional[str], is_global: bool = False) -> Path:
    """Get the path to a ledger directory."""
    if is_global:
        return Path.home() / ".claude" / "ledger"
    elif project_dir:
        return Path(project_dir) / ".claude" / "ledger"
    else:
        return Path.cwd() / ".claude" / "ledger"


def ensure_ledger_structure(ledger_path: Path) -> None:
    """Ensure ledger directory structure exists."""
    ledger_path.mkdir(parents=True, exist_ok=True)
    (ledger_path / "blocks").mkdir(exist_ok=True)

    index_file = ledger_path / "index.json"
    if not index_file.exists():
        write_json(index_file, {"head": None, "blocks": []})

    reinforcements_file = ledger_path / "reinforcements.json"
    if not reinforcements_file.exists():
        write_json(reinforcements_file, {"learnings": {}})


def read_json(path: Path) -> dict:
    """Read JSON from a file."""
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_json(path: Path, data: dict) -> None:
    """Write JSON to a file."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def read_transcript(transcript_path: str) -> list[dict]:
    """Read the session transcript (JSONL format)."""
    events = []
    try:
        with open(transcript_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        pass
    return events


def extract_assistant_messages(events: list[dict]) -> str:
    """Extract all assistant messages from transcript events."""
    messages = []

    for event in events:
        # Handle different event formats
        if event.get("type") == "assistant":
            content = event.get("message", {}).get("content", [])
            for block in content:
                if block.get("type") == "text":
                    messages.append(block.get("text", ""))

        # Alternative format
        elif "content" in event and isinstance(event["content"], list):
            for block in event["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    messages.append(block.get("text", ""))

    return "\n\n".join(messages)


def is_valid_learning(content: str) -> bool:
    """Check if content looks like a valid learning vs noise."""
    # Reject if it looks like a markdown table
    if content.count("|") > 2:
        return False
    # Reject if it's mostly special characters
    alnum_ratio = sum(c.isalnum() or c.isspace() for c in content) / max(len(content), 1)
    if alnum_ratio < 0.6:
        return False
    # Reject if it starts with markdown formatting artifacts
    if content.startswith(("-", "*", "|", "#", "```")):
        return False
    # Reject if it looks like a code snippet
    if content.count("(") > 3 or content.count("{") > 2:
        return False
    # Must have some actual words
    words = [w for w in content.split() if len(w) > 2 and w.isalpha()]
    if len(words) < 3:
        return False
    return True


def extract_learnings(text: str) -> list[dict]:
    """Extract learnings from text using tagged patterns."""
    learnings = []
    seen_content = set()

    # More restrictive patterns - capture until end of sentence/line or next tag
    # Tags should be at start of line or after whitespace
    patterns = {
        LearningCategory.DISCOVERY: re.compile(
            r"(?:^|\n)\s*\[DISCOVERY\]\s*([^\n\[]+?)(?:\.|$|\n|\[)",
            re.IGNORECASE,
        ),
        LearningCategory.DECISION: re.compile(
            r"(?:^|\n)\s*\[DECISION\]\s*([^\n\[]+?)(?:\.|$|\n|\[)",
            re.IGNORECASE,
        ),
        LearningCategory.ERROR: re.compile(
            r"(?:^|\n)\s*\[ERROR\]\s*([^\n\[]+?)(?:\.|$|\n|\[)",
            re.IGNORECASE,
        ),
        LearningCategory.PATTERN: re.compile(
            r"(?:^|\n)\s*\[PATTERN\]\s*([^\n\[]+?)(?:\.|$|\n|\[)",
            re.IGNORECASE,
        ),
    }

    for category, pattern in patterns.items():
        matches = pattern.findall(text)
        for match in matches:
            content = match.strip()
            # Clean up the content
            content = re.sub(r"\s+", " ", content)
            content = content[:500]  # Limit length

            # Validate the content looks like a real learning
            if not content or len(content) < 20 or content in seen_content:
                continue
            if not is_valid_learning(content):
                continue

            seen_content.add(content)

            # Try to extract source file reference
            source = None
            file_match = re.search(r"(?:in|from|at|see)\s+([a-zA-Z0-9_\-./]+\.[a-zA-Z]+)", content)
            if file_match:
                source = file_match.group(1)

            learnings.append({
                "id": str(uuid4()),
                "category": category,
                "content": content,
                "confidence": 0.5,
                "source": source,
                "outcomes": [],
            })

    return learnings


def compute_block_hash(block: dict) -> str:
    """Compute SHA-256 hash of block contents."""
    content = {
        "id": block["id"],
        "timestamp": block["timestamp"],
        "session_id": block["session_id"],
        "parent_block": block["parent_block"],
        "learnings": block["learnings"],
    }
    content_str = json.dumps(content, sort_keys=True, default=str)
    return hashlib.sha256(content_str.encode()).hexdigest()


def append_block(ledger_path: Path, session_id: str, learnings: list[dict]) -> Optional[dict]:
    """Append a new block to the ledger."""
    if not learnings:
        return None

    ensure_ledger_structure(ledger_path)

    index_file = ledger_path / "index.json"
    index = read_json(index_file)

    head = index.get("head")
    block_id = str(uuid4())[:8]

    block = {
        "id": block_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id,
        "parent_block": head,
        "learnings": learnings,
    }
    block["hash"] = compute_block_hash(block)

    # Write block
    block_file = ledger_path / "blocks" / f"{block_id}.json"
    write_json(block_file, block)

    # Update index
    index["head"] = block_id
    index["blocks"].append({
        "id": block_id,
        "timestamp": block["timestamp"],
        "hash": block["hash"],
        "parent": head,
    })
    write_json(index_file, index)

    # Update reinforcements
    reinforcements_file = ledger_path / "reinforcements.json"
    reinforcements = read_json(reinforcements_file)

    for learning in learnings:
        reinforcements["learnings"][learning["id"]] = {
            "category": learning["category"],
            "confidence": learning["confidence"],
            "outcome_count": 0,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    write_json(reinforcements_file, reinforcements)

    return block


def get_modified_files(project_dir: Path) -> list[str]:
    """Get list of modified files using git.

    Args:
        project_dir: The project directory.

    Returns:
        List of file paths that have been modified.
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


def extract_tasks_from_text(text: str) -> tuple[list[str], list[str]]:
    """Extract completed and pending tasks from assistant text.

    Args:
        text: The assistant messages text.

    Returns:
        Tuple of (completed_tasks, pending_tasks).
    """
    completed = []
    pending = []

    # Look for common task patterns
    # Completed patterns
    completed_patterns = [
        r"(?:completed|done|finished|implemented|created|added|fixed|updated):\s*(.+?)(?:\n|$)",
        r"I(?:'ve| have)\s+(?:completed|done|finished|implemented|created|added|fixed|updated)\s+(.+?)(?:\.|$)",
        r"^\s*-\s*\[x\]\s*(.+?)$",  # Checkbox completed
    ]

    # Pending patterns
    pending_patterns = [
        r"(?:todo|remaining|still need to|next|pending):\s*(.+?)(?:\n|$)",
        r"(?:still need to|should still|remaining to)\s+(.+?)(?:\.|$)",
        r"^\s*-\s*\[\s*\]\s*(.+?)$",  # Checkbox unchecked
    ]

    for pattern in completed_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            task = match.strip()[:200]  # Limit length
            if task and len(task) > 10:
                completed.append(task)

    for pattern in pending_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            task = match.strip()[:200]
            if task and len(task) > 10:
                pending.append(task)

    # Deduplicate
    return list(dict.fromkeys(completed))[:10], list(dict.fromkeys(pending))[:10]


def extract_blockers_from_text(text: str) -> list[str]:
    """Extract blockers from assistant text.

    Args:
        text: The assistant messages text.

    Returns:
        List of blockers.
    """
    blockers = []

    blocker_patterns = [
        r"(?:blocked by|blocker|blocking issue|cannot proceed|waiting for):\s*(.+?)(?:\n|$)",
        r"(?:issue|problem|error):\s*(.+?)(?:\n|$)",
    ]

    for pattern in blocker_patterns:
        matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            blocker = match.strip()[:200]
            if blocker and len(blocker) > 10:
                blockers.append(blocker)

    return list(dict.fromkeys(blockers))[:5]


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
        lines.append(context_notes if context_notes else "Pre-compaction handoff saved automatically.")
        lines.append("")

        content = "\n".join(lines)
        file_path.write_text(content, encoding="utf-8")

        return file_path
    except Exception:
        return None


def main():
    """Main hook entry point."""
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        # Output empty to allow compaction to proceed
        print(json.dumps({}))
        sys.exit(0)

    session_id = input_data.get("session_id", str(uuid4()))
    transcript_path = input_data.get("transcript_path", "")
    cwd = input_data.get("cwd", "")

    # Determine project directory early
    project_dir = Path(cwd) if cwd else Path.cwd()

    # Skip if no transcript
    if not transcript_path:
        print(json.dumps({}))
        sys.exit(0)

    # Read and parse transcript
    events = read_transcript(transcript_path)
    if not events:
        print(json.dumps({}))
        sys.exit(0)

    # Extract assistant messages
    assistant_text = extract_assistant_messages(events)
    if not assistant_text:
        print(json.dumps({}))
        sys.exit(0)

    # Extract learnings
    learnings = extract_learnings(assistant_text)

    output = {}
    messages = []

    if learnings:
        # Check if we're in a project with a .claude directory
        if (project_dir / ".claude").exists() or (project_dir / "pyproject.toml").exists() or (project_dir / "package.json").exists():
            ledger_path = get_ledger_path(str(project_dir), is_global=False)
        else:
            # Use global ledger
            ledger_path = get_ledger_path(None, is_global=True)

        # Append block
        block = append_block(ledger_path, session_id + "-precompact", learnings)

        if block:
            # Log to stderr (won't affect hook output)
            print(f"[continuous-claude] PreCompact: Extracted {len(learnings)} learnings -> block {block['id']}", file=sys.stderr)
            messages.append(f"Captured {len(learnings)} learnings to ledger.")

    # Save handoff before compaction
    try:
        # Extract task information from the transcript
        completed_tasks, pending_tasks = extract_tasks_from_text(assistant_text)
        blockers = extract_blockers_from_text(assistant_text)
        modified_files = get_modified_files(project_dir)

        handoff_path = save_handoff(
            project_dir=project_dir,
            session_id=session_id,
            completed_tasks=completed_tasks,
            pending_tasks=pending_tasks,
            blockers=blockers,
            modified_files=modified_files,
            context_notes="Pre-compaction handoff saved automatically.",
        )

        if handoff_path:
            print(f"[continuous-claude] PreCompact: Saved handoff -> {handoff_path}", file=sys.stderr)
            messages.append(f"Saved handoff with {len(modified_files)} modified files.")
    except Exception as e:
        print(f"[continuous-claude] PreCompact: Failed to save handoff: {e}", file=sys.stderr)

    # Combine messages for output
    if messages:
        output["message"] = " ".join(messages)

    # Output result (empty dict or with message)
    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
