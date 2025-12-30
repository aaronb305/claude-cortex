#!/usr/bin/env python3
"""
PreCompact hook for continuous-claude-custom.

Extracts learnings from the conversation BEFORE compaction happens,
ensuring no learnings are lost when the context gets summarized.

Also saves a handoff to capture work-in-progress state and a summary
to preserve conversation context across compactions.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from shared import (
    append_block,
    extract_assistant_messages,
    extract_blockers_from_text,
    extract_learnings,
    extract_tasks_from_text,
    get_ledger_path,
    get_modified_files,
    read_transcript,
    save_handoff,
    write_json,
)


# -----------------------------------------------------------------------------
# Summary-specific functions (not in shared.py)
# -----------------------------------------------------------------------------

def extract_decisions_from_text(text: str) -> list[str]:
    """Extract key decisions from transcript text.

    Args:
        text: The assistant messages text.

    Returns:
        List of decisions identified.
    """
    decisions = []
    seen = set()

    patterns = [
        r"(?:I(?:'ve| have)?\s+)?decided to\s+(.+?)(?:\.|$)",
        r"(?:I(?:'ll| will)?\s+)?(?:chose|choose) to\s+(.+?)(?:\.|$)",
        r"\[DECISION\]\s*(.+?)(?:\.|$|\n|\[)",
        r"(?:The|My)\s+approach (?:is|will be) to\s+(.+?)(?:\.|$)",
        r"(?:I(?:'m| am)?\s+)?going with\s+(.+?)(?:\.|$)",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
        for match in matches:
            decision = match.strip()
            decision = re.sub(r"\s+", " ", decision)[:200]
            if decision and len(decision) > 15 and decision.lower() not in seen:
                seen.add(decision.lower())
                decisions.append(decision)

    return decisions[:10]


def extract_files_from_text(text: str) -> list[str]:
    """Extract file paths discussed in the transcript.

    Args:
        text: The assistant messages text.

    Returns:
        List of file paths mentioned.
    """
    files = set()

    patterns = [
        r"(?:reading|read|wrote|writing|created|modified|updated|editing|edited)\s+[`\"']?([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)[`\"']?",
        r"(?:in|from|at|see|file)\s+[`\"']?([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)[`\"']?",
        r"[`\"']([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]{1,5})[`\"']",
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            file_path = match.strip()
            if (
                file_path
                and len(file_path) > 3
                and not file_path.startswith("http")
                and "/" not in file_path[:2]
                and not file_path.endswith(".0")
            ):
                files.add(file_path)

    return sorted(list(files))[:30]


def generate_summary_text(text: str) -> str:
    """Generate a summary of the conversation.

    This creates a brief summary from the conversation content.

    Args:
        text: The assistant messages text.

    Returns:
        A summary string.
    """
    # Take the first and last substantial paragraphs
    paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]

    if not paragraphs:
        return "Session with no substantial text content."

    summary_parts = []

    # First paragraph (what we started with)
    if paragraphs:
        first = paragraphs[0][:300]
        if len(paragraphs[0]) > 300:
            first += "..."
        summary_parts.append(first)

    # Last paragraph (where we ended up)
    if len(paragraphs) > 1:
        last = paragraphs[-1][:300]
        if len(paragraphs[-1]) > 300:
            last += "..."
        summary_parts.append(last)

    return "\n\n".join(summary_parts)


def save_summary(
    project_dir: Path,
    session_id: str,
    summary_text: str,
    key_decisions: list[str],
    files_discussed: list[str],
    learning_ids: list[str],
) -> Optional[Path]:
    """Save a summary to disk.

    Args:
        project_dir: The project directory.
        session_id: The session identifier.
        summary_text: The summary text.
        key_decisions: List of key decisions.
        files_discussed: List of files discussed.
        learning_ids: List of learning IDs captured.

    Returns:
        Path to the saved summary file, or None if failed.
    """
    try:
        summaries_dir = project_dir / ".claude" / "summaries" / session_id
        summaries_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc)
        timestamp_str = timestamp.strftime("%Y%m%d-%H%M%S")
        filename = f"summary-{timestamp_str}.json"
        file_path = summaries_dir / filename

        data = {
            "session_id": session_id,
            "timestamp": timestamp.isoformat(),
            "summary_text": summary_text,
            "key_decisions": key_decisions,
            "files_discussed": files_discussed,
            "learning_ids": learning_ids,
        }

        write_json(file_path, data)
        return file_path
    except Exception:
        return None


# -----------------------------------------------------------------------------
# Main entry point
# -----------------------------------------------------------------------------

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

    # Save summary before compaction
    try:
        key_decisions = extract_decisions_from_text(assistant_text)
        files_discussed = extract_files_from_text(assistant_text)
        summary_text = generate_summary_text(assistant_text)

        # Collect learning IDs from extracted learnings
        learning_ids = [l["id"] for l in learnings] if learnings else []

        summary_path = save_summary(
            project_dir=project_dir,
            session_id=session_id,
            summary_text=summary_text,
            key_decisions=key_decisions,
            files_discussed=files_discussed,
            learning_ids=learning_ids,
        )

        if summary_path:
            print(f"[continuous-claude] PreCompact: Saved summary -> {summary_path}", file=sys.stderr)
            messages.append(f"Saved summary with {len(key_decisions)} decisions and {len(files_discussed)} files.")
    except Exception as e:
        print(f"[continuous-claude] PreCompact: Failed to save summary: {e}", file=sys.stderr)

    # Combine messages for output
    status_msg = " ".join(messages) if messages else ""

    # Add prompt injection asking Claude to tag untagged learnings
    # This is the safety net before context compaction
    tagging_prompt = """

⚠️ **Context compaction imminent** - Before your context is summarized, please review this session for any untagged learnings:

1. **Bugs fixed** → `[ERROR] what caused it and how to avoid`
2. **Decisions made** → `[DECISION] what was chosen and why`
3. **Discoveries** → `[DISCOVERY] new insight about how something works`
4. **Patterns identified** → `[PATTERN] reusable solution`

If you've already tagged all learnings, acknowledge this. If there are untagged insights from this session, tag them now before they're lost to compaction."""

    output["message"] = status_msg + tagging_prompt

    # Output result
    print(json.dumps(output))
    sys.exit(0)


if __name__ == "__main__":
    main()
