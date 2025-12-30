#!/usr/bin/env python3
"""
Shared utilities for continuous-claude-custom hooks.

This module consolidates all duplicated code from the hooks to provide
a single source of truth for common operations like ledger access,
transcript parsing, learning extraction, and handoff management.

File locking is used for all ledger write operations to prevent race conditions.
"""

import fcntl
import hashlib
import json
import re
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4


# -----------------------------------------------------------------------------
# Try to import from the main package for types and models.
# If import fails (e.g., package not installed), we define local equivalents.
# -----------------------------------------------------------------------------

# Track availability of packages (set lazily)
_PACKAGE_AVAILABLE: Optional[bool] = None
_ANALYSIS_AVAILABLE: Optional[bool] = None
_SearchIndex = None
_TranscriptAnalyzer = None
_SessionInsights = None


def _init_package_imports():
    """Lazily initialize package imports to avoid loading heavy deps at module load."""
    global _PACKAGE_AVAILABLE, _SearchIndex

    if _PACKAGE_AVAILABLE is not None:
        return _PACKAGE_AVAILABLE

    try:
        _src_path = Path(__file__).parent.parent / "src"
        if _src_path.exists() and str(_src_path) not in sys.path:
            sys.path.insert(0, str(_src_path))

        from continuous_claude.search import SearchIndex
        _SearchIndex = SearchIndex
        _PACKAGE_AVAILABLE = True
    except ImportError:
        _SearchIndex = None
        _PACKAGE_AVAILABLE = False

    return _PACKAGE_AVAILABLE


def _init_analysis_imports():
    """Lazily initialize analysis imports (triggers ML dependencies)."""
    global _ANALYSIS_AVAILABLE, _TranscriptAnalyzer, _SessionInsights

    if _ANALYSIS_AVAILABLE is not None:
        return _ANALYSIS_AVAILABLE

    # First ensure package is available
    if not _init_package_imports():
        _ANALYSIS_AVAILABLE = False
        return False

    try:
        from continuous_claude.analysis import TranscriptAnalyzer, SessionInsights
        _TranscriptAnalyzer = TranscriptAnalyzer
        _SessionInsights = SessionInsights
        _ANALYSIS_AVAILABLE = True
    except ImportError:
        _TranscriptAnalyzer = None
        _SessionInsights = None
        _ANALYSIS_AVAILABLE = False

    return _ANALYSIS_AVAILABLE


# Define LearningCategory locally to avoid import dependency
class LearningCategory:
    """Learning category constants."""
    DISCOVERY = "discovery"
    DECISION = "decision"
    ERROR = "error"
    PATTERN = "pattern"


def get_search_index(db_path):
    """Get SearchIndex instance with lazy loading."""
    _init_package_imports()
    if _SearchIndex is None:
        raise ImportError("SearchIndex not available")
    return _SearchIndex(db_path)


# For backwards compatibility - these will be evaluated when accessed
# NOTE: Code should use _init_package_imports() or _init_analysis_imports() directly
PACKAGE_AVAILABLE = None  # Placeholder - use _init_package_imports() instead
ANALYSIS_AVAILABLE = None  # Placeholder - use _init_analysis_imports() instead


# -----------------------------------------------------------------------------
# Path utilities
# -----------------------------------------------------------------------------

def get_ledger_path(project_dir: Optional[str], is_global: bool = False) -> Path:
    """Get the path to a ledger directory.

    Args:
        project_dir: The project directory path, or None to use cwd.
        is_global: If True, return the global ledger path (~/.claude/ledger).

    Returns:
        Path to the ledger directory.
    """
    if is_global:
        return Path.home() / ".claude" / "ledger"
    elif project_dir:
        return Path(project_dir) / ".claude" / "ledger"
    else:
        return Path.cwd() / ".claude" / "ledger"


def get_search_db_path(ledger_path: Path) -> Path:
    """Get the path to the search database for a ledger.

    Args:
        ledger_path: Path to the ledger directory.

    Returns:
        Path to the SQLite search database.
    """
    cache_dir = ledger_path.parent / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir / "search.db"


# -----------------------------------------------------------------------------
# File locking utilities
# -----------------------------------------------------------------------------

@contextmanager
def file_lock(path: Path, exclusive: bool = True):
    """Context manager for file locking using fcntl.

    Args:
        path: Path to the file to lock.
        exclusive: If True, acquire exclusive lock. Otherwise, shared lock.

    Yields:
        The file handle with the lock held.
    """
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock_file = open(lock_path, "w")
    try:
        lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(lock_file.fileno(), lock_type)
        yield lock_file
    finally:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        lock_file.close()


# -----------------------------------------------------------------------------
# JSON utilities with locking
# -----------------------------------------------------------------------------

def read_json(path: Path) -> dict:
    """Read JSON from a file (no locking, for read-only access).

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON data, or empty dict on error.
    """
    try:
        with open(path) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_json(path: Path, data: dict) -> None:
    """Write JSON to a file (no locking, for simple writes).

    Args:
        path: Path to the JSON file.
        data: Data to serialize and write.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def read_json_locked(path: Path) -> dict:
    """Read JSON from a file with shared file lock.

    Args:
        path: Path to the JSON file.

    Returns:
        Parsed JSON data, or empty dict on error.
    """
    try:
        with file_lock(path, exclusive=False):
            return read_json(path)
    except Exception:
        return {}


def write_json_locked(path: Path, data: dict) -> None:
    """Write JSON to a file with exclusive file lock.

    Args:
        path: Path to the JSON file.
        data: Data to serialize and write.
    """
    with file_lock(path, exclusive=True):
        write_json(path, data)


# -----------------------------------------------------------------------------
# Ledger structure utilities
# -----------------------------------------------------------------------------

def ensure_ledger_structure(ledger_path: Path) -> None:
    """Ensure ledger directory structure exists.

    Creates the ledger directory, blocks subdirectory, index.json,
    and reinforcements.json if they don't exist.

    Args:
        ledger_path: Path to the ledger directory.
    """
    ledger_path.mkdir(parents=True, exist_ok=True)
    (ledger_path / "blocks").mkdir(exist_ok=True)

    index_file = ledger_path / "index.json"
    if not index_file.exists():
        write_json(index_file, {"head": None, "blocks": []})

    reinforcements_file = ledger_path / "reinforcements.json"
    if not reinforcements_file.exists():
        write_json(reinforcements_file, {"learnings": {}})


# -----------------------------------------------------------------------------
# Transcript utilities
# -----------------------------------------------------------------------------

def read_transcript(transcript_path: str) -> list[dict]:
    """Read the session transcript (JSONL format).

    Args:
        transcript_path: Path to the transcript file.

    Returns:
        List of event dictionaries parsed from the transcript.
    """
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
    """Extract all assistant messages from transcript events.

    Handles multiple event formats that may appear in transcripts.

    Args:
        events: List of event dictionaries from the transcript.

    Returns:
        Concatenated text from all assistant messages.
    """
    messages = []

    for event in events:
        # Handle standard event format
        if event.get("type") == "assistant":
            content = event.get("message", {}).get("content", [])
            for block in content:
                if block.get("type") == "text":
                    messages.append(block.get("text", ""))

        # Handle alternative format
        elif "content" in event and isinstance(event["content"], list):
            for block in event["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    messages.append(block.get("text", ""))

    return "\n\n".join(messages)


# -----------------------------------------------------------------------------
# Learning validation and extraction
# -----------------------------------------------------------------------------

def is_valid_learning(content: str) -> bool:
    """Check if content looks like a valid learning vs noise.

    Applies heuristics to filter out markdown artifacts, code snippets,
    and other non-learning content.

    Args:
        content: The extracted content to validate.

    Returns:
        True if the content appears to be a valid learning.
    """
    if not content:
        return False

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


# Compiled regex patterns for learning extraction
_LEARNING_PATTERNS = {
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


def extract_learnings(text: str) -> list[dict]:
    """Extract learnings from text using tagged patterns.

    Looks for [DISCOVERY], [DECISION], [ERROR], and [PATTERN] tags
    and extracts the associated content.

    Args:
        text: Text to extract learnings from (typically assistant messages).

    Returns:
        List of learning dictionaries with id, category, content, confidence,
        source, and outcomes fields.
    """
    learnings = []
    seen_content = set()

    for category, pattern in _LEARNING_PATTERNS.items():
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
            file_match = re.search(
                r"(?:in|from|at|see)\s+([a-zA-Z0-9_\-./]+\.[a-zA-Z]+)",
                content
            )
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


# -----------------------------------------------------------------------------
# Block hash computation
# -----------------------------------------------------------------------------

def compute_block_hash(block: dict) -> str:
    """Compute SHA-256 hash of block contents.

    Creates a deterministic hash based on the block's immutable fields.

    Args:
        block: Block dictionary with id, timestamp, session_id, parent_block,
               and learnings fields.

    Returns:
        Hexadecimal SHA-256 hash string.
    """
    content = {
        "id": block["id"],
        "timestamp": block["timestamp"],
        "session_id": block["session_id"],
        "parent_block": block["parent_block"],
        "learnings": block["learnings"],
    }
    content_str = json.dumps(content, sort_keys=True, default=str)
    return hashlib.sha256(content_str.encode()).hexdigest()


# -----------------------------------------------------------------------------
# Search indexing
# -----------------------------------------------------------------------------

def index_learnings_to_search(ledger_path: Path, learnings: list[dict]) -> None:
    """Add learnings to the search index.

    Silently fails if the search module is not available or indexing fails,
    as search indexing should not block ledger operations.
    Uses batch commits for better performance.

    Args:
        ledger_path: Path to the ledger directory.
        learnings: List of learning dictionaries to index.
    """
    if not _init_package_imports() or _SearchIndex is None:
        return

    try:
        db_path = get_search_db_path(ledger_path)
        index = _SearchIndex(db_path)

        for learning in learnings:
            index.index_learning(
                learning_id=learning["id"],
                category=learning["category"],
                content=learning["content"],
                confidence=learning["confidence"],
                source=learning.get("source"),
                commit=False,  # Batch operation
            )
        # Single commit at the end
        index.connection.commit()
        index.close()
    except Exception:
        # Don't fail block creation if indexing fails
        pass


# -----------------------------------------------------------------------------
# Block append with locking and search indexing
# -----------------------------------------------------------------------------

def append_block(
    ledger_path: Path,
    session_id: str,
    learnings: list[dict],
) -> Optional[dict]:
    """Append a new block to the ledger with file locking and search indexing.

    This is the main entry point for adding learnings to the ledger from hooks.
    It handles:
    - Ensuring ledger structure exists
    - File locking to prevent race conditions
    - Creating and writing the block
    - Updating the index and reinforcements files
    - Indexing learnings for full-text search

    Args:
        ledger_path: Path to the ledger directory.
        session_id: ID of the session creating this block.
        learnings: List of learning dictionaries to include in the block.

    Returns:
        The created block dictionary, or None if no learnings provided.
    """
    if not learnings:
        return None

    ensure_ledger_structure(ledger_path)

    index_file = ledger_path / "index.json"
    reinforcements_file = ledger_path / "reinforcements.json"

    # Use file lock for the entire block creation operation
    with file_lock(index_file, exclusive=True):
        index = read_json(index_file)

        head = index.get("head")
        block_id = str(uuid4())[:8]
        timestamp = datetime.now(timezone.utc).isoformat()

        block = {
            "id": block_id,
            "timestamp": timestamp,
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
            "timestamp": timestamp,
            "hash": block["hash"],
            "parent": head,
        })
        write_json(index_file, index)

        # Update reinforcements
        reinforcements = read_json(reinforcements_file)
        for learning in learnings:
            reinforcements["learnings"][learning["id"]] = {
                "category": learning["category"],
                "confidence": learning["confidence"],
                "outcome_count": 0,
                "last_updated": timestamp,
            }
        write_json(reinforcements_file, reinforcements)

    # Index learnings for search (outside the lock to minimize lock duration)
    index_learnings_to_search(ledger_path, learnings)

    return block


# -----------------------------------------------------------------------------
# Git utilities
# -----------------------------------------------------------------------------

def get_modified_files(project_dir: Path) -> list[str]:
    """Get list of modified files using git.

    Args:
        project_dir: The project directory.

    Returns:
        List of file paths that have been modified according to git status.
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


# -----------------------------------------------------------------------------
# Task and blocker extraction
# -----------------------------------------------------------------------------

# Compiled patterns for task extraction
_COMPLETED_PATTERNS = [
    re.compile(
        r"(?:completed|done|finished|implemented|created|added|fixed|updated):\s*(.+?)(?:\n|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"I(?:'ve| have)\s+(?:completed|done|finished|implemented|created|added|fixed|updated)\s+(.+?)(?:\.|$)",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*-\s*\[x\]\s*(.+?)$", re.MULTILINE),
]

_PENDING_PATTERNS = [
    re.compile(
        r"(?:todo|remaining|still need to|next|pending):\s*(.+?)(?:\n|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:still need to|should still|remaining to)\s+(.+?)(?:\.|$)",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*-\s*\[\s*\]\s*(.+?)$", re.MULTILINE),
]


def extract_tasks_from_text(text: str) -> tuple[list[str], list[str]]:
    """Extract completed and pending tasks from assistant text.

    Looks for common task patterns in the text, including markdown checkboxes
    and natural language patterns.

    Args:
        text: The assistant messages text.

    Returns:
        Tuple of (completed_tasks, pending_tasks), each limited to 10 items.
    """
    completed = []
    pending = []

    for pattern in _COMPLETED_PATTERNS:
        matches = pattern.findall(text)
        for match in matches:
            task = match.strip()[:200]  # Limit length
            if task and len(task) > 10:
                completed.append(task)

    for pattern in _PENDING_PATTERNS:
        matches = pattern.findall(text)
        for match in matches:
            task = match.strip()[:200]
            if task and len(task) > 10:
                pending.append(task)

    # Deduplicate while preserving order
    return list(dict.fromkeys(completed))[:10], list(dict.fromkeys(pending))[:10]


# Compiled patterns for blocker extraction
_BLOCKER_PATTERNS = [
    re.compile(
        r"(?:blocked by|blocker|blocking issue|cannot proceed|waiting for):\s*(.+?)(?:\n|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:issue|problem|error):\s*(.+?)(?:\n|$)",
        re.IGNORECASE,
    ),
]


def extract_blockers_from_text(text: str) -> list[str]:
    """Extract blockers from assistant text.

    Looks for patterns indicating blocking issues or problems.

    Args:
        text: The assistant messages text.

    Returns:
        List of blockers, limited to 5 items.
    """
    blockers = []

    for pattern in _BLOCKER_PATTERNS:
        matches = pattern.findall(text)
        for match in matches:
            blocker = match.strip()[:200]
            if blocker and len(blocker) > 10:
                blockers.append(blocker)

    return list(dict.fromkeys(blockers))[:5]


# -----------------------------------------------------------------------------
# Handoff management
# -----------------------------------------------------------------------------

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
    except Exception:
        return None


# -----------------------------------------------------------------------------
# Handoff loading and parsing
# -----------------------------------------------------------------------------

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

    except Exception:
        return None


# -----------------------------------------------------------------------------
# Project type detection
# -----------------------------------------------------------------------------

def detect_project_type(project_dir: Path) -> dict:
    """Detect project type and package manager.

    Args:
        project_dir: The project directory.

    Returns:
        Dictionary with type, package_manager, and commands fields.
    """
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


# -----------------------------------------------------------------------------
# Learnings query utilities
# -----------------------------------------------------------------------------

def get_learnings_by_confidence(
    ledger_path: Path,
    min_confidence: float = 0.5,
    limit: int = 15,
) -> list[dict]:
    """Get learnings sorted by confidence.

    Args:
        ledger_path: Path to the ledger directory.
        min_confidence: Minimum confidence threshold.
        limit: Maximum number of results.

    Returns:
        List of learning summaries with confidence scores.
    """
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
    """Get the actual content of a learning from blocks.

    Args:
        ledger_path: Path to the ledger directory.
        learning_id: ID of the learning to retrieve.

    Returns:
        The learning content, or None if not found.
    """
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


# -----------------------------------------------------------------------------
# LLM-powered session analysis
# -----------------------------------------------------------------------------

def analyze_session(
    transcript_path: str,
    session_id: str,
    use_llm: bool = True,
    save_insights: bool = True,
    project_dir: Optional[Path] = None,
) -> Optional[dict]:
    """Analyze a session transcript and extract structured insights.

    This provides Braintrust-like learning extraction using LLM analysis
    of the full transcript, not just tagged content.

    Args:
        transcript_path: Path to the transcript file.
        session_id: Session identifier.
        use_llm: Whether to use LLM for analysis (vs regex fallback).
        save_insights: Whether to save insights to disk.
        project_dir: Project directory for saving insights.

    Returns:
        Dictionary with insights, or None if analysis failed.
    """
    if not _init_analysis_imports():
        return None

    try:
        transcript_file = Path(transcript_path)
        if not transcript_file.exists():
            return None

        # Create analyzer (lazy import already done)
        analyzer = _TranscriptAnalyzer(use_llm=use_llm)

        # Analyze transcript
        insights = analyzer.analyze_from_file(transcript_file, session_id)

        # Save insights if requested
        if save_insights and project_dir:
            insights_dir = project_dir / ".claude" / "insights" / session_id
            from continuous_claude.analysis.transcript import save_insights as _save
            _save(insights, insights_dir)

        return insights.to_dict()
    except Exception:
        return None


def insights_to_learnings(insights_dict: dict) -> list[dict]:
    """Convert session insights to learning format for ledger storage.

    Args:
        insights_dict: Dictionary from analyze_session()

    Returns:
        List of learning dicts ready for append_block()
    """
    if not _init_analysis_imports() or not insights_dict:
        return []

    try:
        insights = _SessionInsights(
            session_id=insights_dict.get("session_id", "unknown"),
            what_worked=insights_dict.get("what_worked", []),
            what_failed=insights_dict.get("what_failed", []),
            patterns=insights_dict.get("patterns", []),
            key_decisions=insights_dict.get("key_decisions", []),
        )
        return insights.to_learnings()
    except Exception:
        return []


# -----------------------------------------------------------------------------
# Module exports
# -----------------------------------------------------------------------------

__all__ = [
    # Constants
    "LearningCategory",
    # Lazy init functions (preferred)
    "_init_package_imports",
    "_init_analysis_imports",
    "get_search_index",
    # Path utilities
    "get_ledger_path",
    "get_search_db_path",
    # File locking
    "file_lock",
    # JSON utilities
    "read_json",
    "write_json",
    "read_json_locked",
    "write_json_locked",
    # Ledger utilities
    "ensure_ledger_structure",
    "compute_block_hash",
    "append_block",
    "index_learnings_to_search",
    # Transcript utilities
    "read_transcript",
    "extract_assistant_messages",
    # Learning extraction
    "is_valid_learning",
    "extract_learnings",
    # Git utilities
    "get_modified_files",
    # Task extraction
    "extract_tasks_from_text",
    "extract_blockers_from_text",
    # Handoff management
    "save_handoff",
    "load_latest_handoff",
    "parse_handoff_markdown",
    # Project detection
    "detect_project_type",
    # Learning queries
    "get_learnings_by_confidence",
    "get_learning_content",
    # Session analysis
    "analyze_session",
    "insights_to_learnings",
]
