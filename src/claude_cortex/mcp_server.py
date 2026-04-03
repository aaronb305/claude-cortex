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
            # Get confidence from ledger (use effective confidence with decay)
            conf = ledger.get_effective_confidence(r.learning_id)
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

        new_confidence = ledger.get_effective_confidence(learning.id)

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
        # get_learnings_by_confidence returns list[dict] with keys: id, category, content, confidence, effective_confidence
        all_learnings = ledger.get_learnings_by_confidence(min_confidence, limit=limit * 2)

        results = []
        for l in all_learnings:
            # Filter by category if specified (l is a dict, not Learning object)
            l_category = l["category"]
            if category and l_category != category.lower():
                continue

            entry = {
                "id": l["id"][:8],
                "full_id": l["id"],
                "category": l_category,
                "snippet": l["content"][:100],
                "confidence": round(l.get("effective_confidence", l["confidence"]), 2),
            }

            if show_decay:
                entry["effective_confidence"] = round(l.get("effective_confidence", l["confidence"]), 2)

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
        # Get all learnings with min_confidence=0 to include everything
        all_learnings = ledger.get_learnings_by_confidence(min_confidence=0.0, limit=10000)

        by_category = {}
        by_confidence = {"high": 0, "medium": 0, "low": 0}
        total = 0

        for l in all_learnings:
            total += 1
            # l is a dict with keys: id, category, content, confidence, effective_confidence
            cat = l["category"]
            by_category[cat] = by_category.get(cat, 0) + 1

            conf = l.get("effective_confidence", l["confidence"])
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


# ---------------------------------------------------------------------------
# New v2 tools: Handoff, Suggestions, Tag Learning, Session Summary
# ---------------------------------------------------------------------------


@mcp.tool()
async def get_handoff(
    session_id: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> dict:
    """Get the latest work-in-progress handoff for session continuity.

    Args:
        session_id: Specific session ID, or None for most recent
        project_dir: Project directory, or None for cwd

    Returns:
        Full handoff data including completed, pending, blockers, modified files, context
    """
    try:
        from .handoff import HandoffManager

        pdir = Path(project_dir) if project_dir else Path.cwd()
        manager = HandoffManager(pdir)
        handoff = manager.load_latest_handoff(session_id)

        if not handoff:
            return {"found": False, "message": "No handoff found"}

        return {
            "found": True,
            "session_id": handoff.session_id,
            "timestamp": handoff.timestamp.isoformat(),
            "completed_tasks": handoff.completed_tasks,
            "pending_tasks": handoff.pending_tasks,
            "blockers": handoff.blockers,
            "modified_files": handoff.modified_files,
            "context_notes": handoff.context_notes,
        }

    except Exception as e:
        return {"found": False, "error": str(e)}


@mcp.tool()
async def get_suggestions(
    limit: int = 5,
    min_confidence: float = 0.5,
    project_dir: Optional[str] = None,
) -> dict:
    """Get cross-project learning suggestions from the global ledger.

    Analyzes the current project's type and tech stack to find relevant
    learnings from other projects.

    Args:
        limit: Maximum suggestions to return
        min_confidence: Minimum confidence threshold
        project_dir: Current project directory for context matching

    Returns:
        List of suggested learnings with relevance scores and match reasons
    """
    try:
        from .suggestions import LearningRecommender

        global_ledger_path = get_global_ledger_path()
        if not global_ledger_path.exists():
            return {"suggestions": [], "total": 0}

        global_ledger = Ledger(global_ledger_path, is_global=True)
        recommender = LearningRecommender(global_ledger)

        pdir = Path(project_dir) if project_dir else Path.cwd()
        suggestions = recommender.get_suggestions(pdir, limit=limit, min_confidence=min_confidence)

        results = []
        for s in suggestions:
            learning = s.learning
            results.append({
                "id": learning.id[:8],
                "full_id": learning.id,
                "category": learning.category.value if hasattr(learning.category, 'value') else str(learning.category),
                "content": s.format_summary(max_length=200),
                "confidence": round(learning.confidence, 2),
                "relevance_score": round(s.relevance_score, 2),
                "match_reasons": s.match_reasons[:3],
            })

        return {"suggestions": results, "total": len(results)}

    except Exception as e:
        return {"suggestions": [], "total": 0, "error": str(e)}


@mcp.tool()
async def tag_learning(
    content: str,
    category: str,
    confidence: float = 0.7,
    source_file: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> dict:
    """Tag and store a learning directly in the knowledge ledger.

    Use this to capture insights without embedding [DISCOVERY]/[DECISION]/etc.
    tags in conversation text.

    Args:
        content: The learning content (max 500 chars)
        category: Category: discovery, decision, error, pattern
        confidence: Initial confidence (0.0-1.0, default 0.7)
        source_file: Optional source file reference
        project_dir: Project directory, or None for global ledger

    Returns:
        Created learning ID and confirmation
    """
    from .ledger.models import Learning, LearningCategory
    import uuid

    valid_categories = {"discovery", "decision", "error", "pattern"}
    if category.lower() not in valid_categories:
        return {"error": f"Category must be one of: {', '.join(valid_categories)}"}

    if len(content) > 500:
        content = content[:500]

    confidence = max(0.0, min(1.0, confidence))

    try:
        ledger_path = get_project_ledger_path(project_dir)
        ledger = Ledger(ledger_path)

        learning = Learning(
            id=str(uuid.uuid4()),
            category=LearningCategory(category.lower()),
            content=content,
            source=f"mcp_tag:{source_file}" if source_file else "mcp_tag",
            confidence=confidence,
        )

        block = ledger.append_block(
            session_id="mcp-session",
            learnings=[learning],
        )

        return {
            "status": "created",
            "learning_id": learning.id[:8],
            "full_id": learning.id,
            "category": category.lower(),
            "confidence": confidence,
            "block_id": block.id[:8] if block else None,
        }

    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def get_session_summary(
    session_id: Optional[str] = None,
    limit: int = 3,
    project_dir: Optional[str] = None,
) -> dict:
    """Get recent session summaries for context.

    Args:
        session_id: Specific session, or None for most recent
        limit: Number of summaries to return
        project_dir: Project directory

    Returns:
        List of summaries with decisions, files discussed, and learning IDs
    """
    try:
        from .summaries import SummaryManager

        pdir = Path(project_dir) if project_dir else Path.cwd()
        manager = SummaryManager(pdir)
        summaries = manager.load_recent_summaries(limit=limit, session_id=session_id)

        results = []
        for s in summaries:
            results.append({
                "session_id": s.session_id,
                "timestamp": s.timestamp.isoformat() if hasattr(s.timestamp, 'isoformat') else str(s.timestamp),
                "summary_text": s.summary_text[:300] if s.summary_text else "",
                "key_decisions": s.key_decisions[:5] if hasattr(s, 'key_decisions') else [],
                "files_discussed": s.files_discussed[:10] if hasattr(s, 'files_discussed') else [],
                "learning_ids": s.learning_ids[:10] if hasattr(s, 'learning_ids') else [],
            })

        return {"summaries": results, "total": len(results)}

    except Exception as e:
        return {"summaries": [], "total": 0, "error": str(e)}


# ---------------------------------------------------------------------------
# New v2 tools: Entity Graph (code structure)
# ---------------------------------------------------------------------------


@mcp.tool()
async def entity_search(
    query: str,
    entity_type: Optional[str] = None,
    limit: int = 20,
    project_dir: Optional[str] = None,
) -> dict:
    """Search for code entities (functions, classes, methods) by name.

    Requires entity indexing: run `cclaude entities index .` first.

    Args:
        query: Search query for entity names
        entity_type: Filter by type: file, function, class, method, constant
        limit: Maximum results
        project_dir: Project directory

    Returns:
        List of matching entities with file paths and line numbers
    """
    try:
        from .entities import EntityGraph, EntityType

        pdir = Path(project_dir) if project_dir else Path.cwd()
        db_path = pdir / ".claude" / "cache" / "entities.db"

        if not db_path.exists():
            return {
                "results": [],
                "total": 0,
                "error": "Entity graph not indexed. Run: cclaude entities index .",
            }

        with EntityGraph(db_path=db_path, project_dir=pdir) as graph:
            entities = graph.search(query, limit=limit)

            # Filter by type if specified
            if entity_type:
                try:
                    etype = EntityType(entity_type.lower())
                    entities = [e for e in entities if e.entity_type == etype]
                except ValueError:
                    return {"results": [], "total": 0, "error": f"Invalid entity_type: {entity_type}"}

            results = []
            for e in entities[:limit]:
                results.append({
                    "name": e.name,
                    "qualified_name": e.qualified_name,
                    "type": e.entity_type.value,
                    "file_path": e.file_path,
                    "start_line": e.start_line,
                    "end_line": e.end_line,
                })

            return {"results": results, "total": len(results)}

    except Exception as e:
        return {"results": [], "total": 0, "error": str(e)}


@mcp.tool()
async def entity_show(
    qualified_name: str,
    show_dependencies: bool = False,
    show_dependents: bool = False,
    depth: int = 1,
    project_dir: Optional[str] = None,
) -> dict:
    """Get details of a specific code entity including its relationships.

    Args:
        qualified_name: Full qualified name (file_path:entity_name)
        show_dependencies: Include what this entity depends on
        show_dependents: Include what depends on this entity
        depth: Depth of relationship traversal (1-3)
        project_dir: Project directory

    Returns:
        Entity details with optional dependency/dependent lists
    """
    try:
        from .entities import EntityGraph

        pdir = Path(project_dir) if project_dir else Path.cwd()
        db_path = pdir / ".claude" / "cache" / "entities.db"

        if not db_path.exists():
            return {"error": "Entity graph not indexed. Run: cclaude entities index ."}

        depth = max(1, min(depth, 3))

        with EntityGraph(db_path=db_path, project_dir=pdir) as graph:
            entity = graph.get_entity(qualified_name)
            if not entity:
                return {"error": f"Entity '{qualified_name}' not found"}

            result = {
                "name": entity.name,
                "qualified_name": entity.qualified_name,
                "type": entity.entity_type.value,
                "file_path": entity.file_path,
                "start_line": entity.start_line,
                "end_line": entity.end_line,
                "metadata": entity.metadata,
            }

            if show_dependencies and entity.id:
                deps = graph.get_dependencies(entity.id, depth=depth)
                result["dependencies"] = [
                    {
                        "name": r.target_entity.name if r.target_entity else "unknown",
                        "qualified_name": r.target_entity.qualified_name if r.target_entity else "unknown",
                        "type": r.target_entity.entity_type.value if r.target_entity else "unknown",
                        "relationship": r.relationship_type.value,
                    }
                    for r in deps
                ]

            if show_dependents and entity.id:
                deps = graph.get_dependents(entity.id, depth=depth)
                result["dependents"] = [
                    {
                        "name": r.source_entity.name if r.source_entity else "unknown",
                        "qualified_name": r.source_entity.qualified_name if r.source_entity else "unknown",
                        "type": r.source_entity.entity_type.value if r.source_entity else "unknown",
                        "relationship": r.relationship_type.value,
                    }
                    for r in deps
                ]

            return result

    except Exception as e:
        return {"error": str(e)}


@mcp.tool()
async def entity_stats(project_dir: Optional[str] = None) -> dict:
    """Get statistics about the code entity graph.

    Args:
        project_dir: Project directory

    Returns:
        Counts of entities by type, relationship count, indexed file count
    """
    try:
        from .entities import EntityGraph

        pdir = Path(project_dir) if project_dir else Path.cwd()
        db_path = pdir / ".claude" / "cache" / "entities.db"

        if not db_path.exists():
            return {
                "indexed": False,
                "error": "Entity graph not indexed. Run: cclaude entities index .",
            }

        with EntityGraph(db_path=db_path, project_dir=pdir) as graph:
            stats = graph.get_stats()
            stats["indexed"] = True
            return stats

    except Exception as e:
        return {"indexed": False, "error": str(e)}


def run():
    """Entry point for the MCP server."""
    if not MCP_AVAILABLE:
        print("Error: MCP package not installed. Run: uv add mcp", file=sys.stderr)
        sys.exit(1)

    mcp.run()


if __name__ == "__main__":
    run()
