#!/usr/bin/env python3
"""
MCP Server for Claude Cortex.

Exposes ledger search and management as MCP tools for low-latency
access from Claude Code. Uses STDIO transport for on-demand operation.

Usage:
    python -m claude_cortex.mcp_server
    # Or via uv:
    uv run python -m claude_cortex.mcp_server
"""

import sys
from pathlib import Path
from typing import Optional

try:
    from mcp.server.fastmcp import FastMCP
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False
    # Stub for when MCP is not installed
    class FastMCP:
        def __init__(self, name: str):
            self.name = name
        def tool(self):
            def decorator(func):
                return func
            return decorator
        def run(self):
            pass

from .ledger import Ledger
from .search import SearchIndex


def get_global_ledger_path() -> Path:
    """Get path to global ledger."""
    return Path.home() / ".claude" / "ledger"


def get_cache_dir() -> Path:
    """Get path to cache directory."""
    return Path.home() / ".claude" / "cache"


def get_project_ledger_path(project_dir: Optional[str] = None) -> Path:
    """Get path to project ledger."""
    if project_dir:
        return Path(project_dir) / ".claude" / "ledger"
    return get_global_ledger_path()


# Initialize MCP server
mcp = FastMCP(name="claude-cortex")


@mcp.tool()
async def search_learnings(
    query: str,
    category: Optional[str] = None,
    min_confidence: float = 0.5,
    limit: int = 10,
    project_dir: Optional[str] = None,
) -> dict:
    """Search the knowledge ledger using full-text search.

    Args:
        query: Full-text search query (uses SQLite FTS5)
        category: Filter by category: discovery, decision, error, pattern
        min_confidence: Minimum confidence threshold (0.0-1.0)
        limit: Maximum number of results
        project_dir: Project directory for project-specific search, or None for global

    Returns:
        Dictionary with matching learnings including IDs, snippets, and confidence scores
    """
    try:
        cache_dir = get_cache_dir()
        ledger_path = get_project_ledger_path(project_dir)

        if not ledger_path.exists():
            return {"results": [], "total": 0, "error": None}

        ledger = Ledger(ledger_path)

        # Use search index if available
        try:
            with SearchIndex(cache_dir) as index:
                if category:
                    results = index.search_by_category(query, category, limit=limit * 2)
                else:
                    results = index.search(query, limit=limit * 2)
        except Exception:
            # Fallback to ledger search
            results = []

        # Filter by confidence and limit
        filtered = []
        for r in results:
            # Get confidence from ledger
            conf = ledger.get_confidence(r.learning_id)
            if conf >= min_confidence:
                filtered.append({
                    "id": r.learning_id[:8],
                    "full_id": r.learning_id,
                    "snippet": r.snippet[:150] if hasattr(r, 'snippet') else r.content[:150],
                    "category": r.category if hasattr(r, 'category') else "unknown",
                    "confidence": round(conf, 2),
                    "rank": r.rank if hasattr(r, 'rank') else 0,
                })
                if len(filtered) >= limit:
                    break

        return {
            "query": query,
            "category": category,
            "results": filtered,
            "total": len(filtered),
        }

    except Exception as e:
        return {"results": [], "total": 0, "error": str(e)}


@mcp.tool()
async def get_learning(
    learning_id: str,
    show_outcomes: bool = False,
    show_decay: bool = False,
    project_dir: Optional[str] = None,
) -> dict:
    """Get full details of a specific learning by ID.

    Args:
        learning_id: Full or partial learning ID (prefix match supported)
        show_outcomes: Include outcome history
        show_decay: Include effective confidence with decay calculation
        project_dir: Project directory, or None for global ledger

    Returns:
        Complete learning with content, metadata, and optionally outcomes
    """
    try:
        ledger_path = get_project_ledger_path(project_dir)

        if not ledger_path.exists():
            return {"error": f"Ledger not found at {ledger_path}"}

        ledger = Ledger(ledger_path)
        learning, block = ledger.get_learning_by_id(learning_id, prefix_match=True)

        if not learning:
            return {"error": f"Learning '{learning_id}' not found"}

        result = {
            "id": learning.id,
            "category": learning.category.value if hasattr(learning.category, 'value') else str(learning.category),
            "content": learning.content,
            "confidence": round(learning.confidence, 2),
            "source": learning.source,
            "created": block.timestamp.isoformat() if block and hasattr(block, 'timestamp') else None,
        }

        if show_decay:
            effective = ledger.get_effective_confidence(learning.id)
            result["effective_confidence"] = round(effective, 2)
            result["has_decayed"] = effective < learning.confidence

        if show_outcomes:
            outcomes = ledger.get_learning_outcomes(learning.id)
            result["outcomes"] = outcomes

        return result

    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def record_outcome(
    learning_id: str,
    result: str,
    comment: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> dict:
    """Record outcome for a learning (updates confidence via reinforcement).

    Args:
        learning_id: Learning ID to update
        result: Outcome result - must be "success", "partial", or "failure"
        comment: Optional context about the outcome
        project_dir: Project directory, or None for global ledger

    Returns:
        Status and new confidence score
    """
    valid_results = ("success", "partial", "failure")
    if result not in valid_results:
        return {"error": f"Result must be one of: {', '.join(valid_results)}"}

    try:
        ledger_path = get_project_ledger_path(project_dir)

        if not ledger_path.exists():
            return {"error": f"Ledger not found at {ledger_path}"}

        ledger = Ledger(ledger_path)

        # Verify learning exists
        learning, _ = ledger.get_learning_by_id(learning_id, prefix_match=True)
        if not learning:
            return {"error": f"Learning '{learning_id}' not found"}

        # Record outcome
        ledger.record_outcome(learning.id, result, comment)

        new_confidence = ledger.get_confidence(learning.id)

        return {
            "status": "recorded",
            "learning_id": learning.id[:8],
            "result": result,
            "new_confidence": round(new_confidence, 2),
        }

    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def list_learnings(
    min_confidence: float = 0.5,
    category: Optional[str] = None,
    limit: int = 20,
    show_decay: bool = False,
    project_dir: Optional[str] = None,
) -> dict:
    """List learnings from the ledger sorted by confidence.

    Args:
        min_confidence: Minimum confidence threshold
        category: Filter by category: discovery, decision, error, pattern
        limit: Maximum results
        show_decay: Include effective confidence with decay
        project_dir: Project directory, or None for global ledger

    Returns:
        List of learnings with metadata
    """
    try:
        ledger_path = get_project_ledger_path(project_dir)

        if not ledger_path.exists():
            return {"learnings": [], "total": 0}

        ledger = Ledger(ledger_path)
        all_learnings = ledger.get_learnings_by_confidence(min_confidence, limit=limit * 2)

        results = []
        for l in all_learnings:
            # Filter by category if specified
            l_category = l.category.value if hasattr(l.category, 'value') else str(l.category)
            if category and l_category != category.lower():
                continue

            entry = {
                "id": l.id[:8],
                "full_id": l.id,
                "category": l_category,
                "snippet": l.content[:100],
                "confidence": round(l.confidence, 2),
            }

            if show_decay:
                effective = ledger.get_effective_confidence(l.id)
                entry["effective_confidence"] = round(effective, 2)

            results.append(entry)

            if len(results) >= limit:
                break

        return {
            "learnings": results,
            "total": len(results),
        }

    except Exception as e:
        return {"learnings": [], "total": 0, "error": str(e)}


@mcp.tool()
async def ledger_stats(project_dir: Optional[str] = None) -> dict:
    """Get statistics about the knowledge ledger.

    Args:
        project_dir: Project directory, or None for global ledger

    Returns:
        Statistics including counts by category, confidence distribution, etc.
    """
    try:
        ledger_path = get_project_ledger_path(project_dir)

        if not ledger_path.exists():
            return {"error": "Ledger not found", "exists": False}

        ledger = Ledger(ledger_path)
        all_learnings = ledger.get_all_learnings()

        by_category = {}
        by_confidence = {"high": 0, "medium": 0, "low": 0}
        total = 0

        for l in all_learnings:
            total += 1
            cat = l.category.value if hasattr(l.category, 'value') else str(l.category)
            by_category[cat] = by_category.get(cat, 0) + 1

            conf = l.confidence
            if conf >= 0.7:
                by_confidence["high"] += 1
            elif conf >= 0.4:
                by_confidence["medium"] += 1
            else:
                by_confidence["low"] += 1

        return {
            "exists": True,
            "path": str(ledger_path),
            "total_learnings": total,
            "by_category": by_category,
            "by_confidence": by_confidence,
        }

    except Exception as e:
        return {"error": str(e), "exists": False}


def run():
    """Entry point for the MCP server."""
    if not MCP_AVAILABLE:
        print("Error: MCP package not installed. Run: uv add mcp", file=sys.stderr)
        sys.exit(1)

    mcp.run()


if __name__ == "__main__":
    run()
