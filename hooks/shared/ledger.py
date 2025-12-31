#!/usr/bin/env python3
"""
Ledger operations: structure, block creation, hash computation, and search indexing.
"""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from uuid import uuid4

from .json_utils import read_json, write_json
from .locking import file_lock
from .paths import get_search_db_path


# -----------------------------------------------------------------------------
# Lazy imports for search functionality
# -----------------------------------------------------------------------------

_PACKAGE_AVAILABLE: Optional[bool] = None
_SearchIndex = None


def _init_package_imports():
    """Lazily initialize package imports to avoid loading heavy deps at module load."""
    global _PACKAGE_AVAILABLE, _SearchIndex

    if _PACKAGE_AVAILABLE is not None:
        return _PACKAGE_AVAILABLE

    try:
        _src_path = Path(__file__).parent.parent.parent / "src"
        if _src_path.exists() and str(_src_path) not in sys.path:
            sys.path.insert(0, str(_src_path))

        from continuous_claude.search import SearchIndex
        _SearchIndex = SearchIndex
        _PACKAGE_AVAILABLE = True
    except ImportError:
        _SearchIndex = None
        _PACKAGE_AVAILABLE = False

    return _PACKAGE_AVAILABLE


def get_search_index(db_path):
    """Get SearchIndex instance with lazy loading."""
    _init_package_imports()
    if _SearchIndex is None:
        raise ImportError("SearchIndex not available")
    return _SearchIndex(db_path)


# For backwards compatibility - use _init_package_imports() instead
PACKAGE_AVAILABLE = None  # Placeholder


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

    Logs warnings if the search module is not available or indexing fails,
    as search indexing should not block ledger operations.
    Uses batch commits for better performance.
    Uses file locking to prevent race conditions with concurrent indexing.

    Args:
        ledger_path: Path to the ledger directory.
        learnings: List of learning dictionaries to index.
    """
    if not _init_package_imports() or _SearchIndex is None:
        return

    try:
        db_path = get_search_db_path(ledger_path)
        # Use file lock to prevent concurrent search index modifications
        with file_lock(db_path, exclusive=True):
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
    except Exception as e:
        # Don't fail block creation if indexing fails, but log warning
        print(f"[continuous-claude] Warning: Search indexing failed: {e}", file=sys.stderr)


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

        # Update reinforcements with its own lock to prevent race conditions
        with file_lock(reinforcements_file, exclusive=True):
            reinforcements = read_json(reinforcements_file)
            for learning in learnings:
                reinforcements["learnings"][learning["id"]] = {
                    "category": learning["category"],
                    "content": learning["content"],  # Cache content for O(1) lookup
                    "confidence": learning["confidence"],
                    "outcome_count": 0,
                    "last_updated": timestamp,
                }
            write_json(reinforcements_file, reinforcements)

    # Index learnings for search (outside the lock to minimize lock duration)
    index_learnings_to_search(ledger_path, learnings)

    return block


# -----------------------------------------------------------------------------
# Learning query utilities
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
    """Get the actual content of a learning.

    First checks the reinforcements.json cache for O(1) lookup.
    Falls back to scanning blocks for backwards compatibility with
    learnings created before content caching was added.

    Args:
        ledger_path: Path to the ledger directory.
        learning_id: ID of the learning to retrieve.

    Returns:
        The learning content, or None if not found.
    """
    # First try the fast path: check reinforcements.json cache
    reinforcements_file = ledger_path / "reinforcements.json"
    if reinforcements_file.exists():
        reinforcements = read_json(reinforcements_file)
        learning_data = reinforcements.get("learnings", {}).get(learning_id)
        if learning_data and "content" in learning_data:
            return learning_data["content"]

    # Fallback: scan blocks for backwards compatibility
    blocks_dir = ledger_path / "blocks"
    if not blocks_dir.exists():
        return None

    for block_file in blocks_dir.glob("*.json"):
        try:
            block = read_json(block_file)
            for learning in block.get("learnings", []):
                if learning.get("id") == learning_id:
                    return learning.get("content")
        except Exception as e:
            print(f"[continuous-claude] Warning: Failed to read block {block_file}: {e}", file=sys.stderr)
            continue

    return None


__all__ = [
    # Lazy init
    "_init_package_imports",
    "get_search_index",
    "PACKAGE_AVAILABLE",
    # Structure
    "ensure_ledger_structure",
    # Block operations
    "compute_block_hash",
    "append_block",
    "index_learnings_to_search",
    # Queries
    "get_learnings_by_confidence",
    "get_learning_content",
]
