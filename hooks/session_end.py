#!/usr/bin/env python3
"""
SessionEnd hook for continuous-claude-custom.

Extracts learnings from the session transcript and stores them in the ledger.
"""

import hashlib
import json
import re
import sys
from datetime import datetime
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
        "timestamp": datetime.utcnow().isoformat(),
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
            "last_updated": datetime.utcnow().isoformat(),
        }

    write_json(reinforcements_file, reinforcements)

    return block


def main():
    """Main hook entry point."""
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    session_id = input_data.get("session_id", str(uuid4()))
    transcript_path = input_data.get("transcript_path", "")
    cwd = input_data.get("cwd", "")
    reason = input_data.get("reason", "exit")

    # Skip if no transcript
    if not transcript_path:
        sys.exit(0)

    # Read and parse transcript
    events = read_transcript(transcript_path)
    if not events:
        sys.exit(0)

    # Extract assistant messages
    assistant_text = extract_assistant_messages(events)
    if not assistant_text:
        sys.exit(0)

    # Extract learnings
    learnings = extract_learnings(assistant_text)

    if learnings:
        # Determine ledger path (project or global)
        project_dir = Path(cwd) if cwd else Path.cwd()

        # Check if we're in a project with a .claude directory
        if (project_dir / ".claude").exists() or (project_dir / "pyproject.toml").exists() or (project_dir / "package.json").exists():
            ledger_path = get_ledger_path(str(project_dir), is_global=False)
        else:
            # Use global ledger
            ledger_path = get_ledger_path(None, is_global=True)

        # Append block
        block = append_block(ledger_path, session_id, learnings)

        if block:
            # Log to stderr (won't affect hook output)
            print(f"[continuous-claude] Extracted {len(learnings)} learnings -> block {block['id']}", file=sys.stderr)

    sys.exit(0)


if __name__ == "__main__":
    main()
