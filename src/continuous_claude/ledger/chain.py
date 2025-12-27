"""Ledger chain management for storing and retrieving blocks."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional, TYPE_CHECKING

from .models import Block, Learning, LearningCategory

if TYPE_CHECKING:
    from ..search import SearchIndex
    from ..search.index import SearchResult


class Ledger:
    """Manages a blockchain-style ledger of knowledge blocks."""

    def __init__(self, path: Path, is_global: bool = False):
        """Initialize a ledger at the given path.

        Args:
            path: Directory path for the ledger
            is_global: Whether this is the global ledger (~/.claude/ledger/)
        """
        self.path = path
        self.is_global = is_global
        self.blocks_dir = path / "blocks"
        self.index_file = path / "index.json"
        self.reinforcements_file = path / "reinforcements.json"
        self.imports_file = path / "imports.json"  # Only for project ledgers

        # Search index is lazily initialized
        self._search_index: Optional[SearchIndex] = None

        self._ensure_structure()

    def _ensure_structure(self) -> None:
        """Create ledger directory structure if it doesn't exist."""
        self.path.mkdir(parents=True, exist_ok=True)
        self.blocks_dir.mkdir(exist_ok=True)

        if not self.index_file.exists():
            self._write_json(self.index_file, {"head": None, "blocks": []})

        if not self.reinforcements_file.exists():
            self._write_json(self.reinforcements_file, {"learnings": {}})

        if not self.is_global and not self.imports_file.exists():
            self._write_json(self.imports_file, {"imports": []})

    def _read_json(self, path: Path) -> dict:
        """Read JSON from a file."""
        with open(path) as f:
            return json.load(f)

    def _write_json(self, path: Path, data: dict) -> None:
        """Write JSON to a file."""
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def get_head(self) -> Optional[str]:
        """Get the ID of the most recent block."""
        index = self._read_json(self.index_file)
        return index.get("head")

    def get_block(self, block_id: str) -> Optional[Block]:
        """Retrieve a block by its ID."""
        block_file = self.blocks_dir / f"{block_id}.json"
        if not block_file.exists():
            return None

        data = self._read_json(block_file)
        return Block.model_validate(data)

    def append_block(self, session_id: str, learnings: list[Learning]) -> Block:
        """Create and append a new block to the chain.

        Args:
            session_id: ID of the Claude session
            learnings: List of learnings to include in the block

        Returns:
            The newly created block
        """
        index = self._read_json(self.index_file)
        head = index.get("head")

        block = Block(
            session_id=session_id,
            parent_block=head,
            learnings=learnings,
        )

        # Write block to file
        block_file = self.blocks_dir / f"{block.id}.json"
        self._write_json(block_file, block.model_dump(mode="json"))

        # Update index
        index["head"] = block.id
        index["blocks"].append({
            "id": block.id,
            "timestamp": block.timestamp.isoformat(),
            "hash": block.hash,
            "parent": head,
        })
        self._write_json(self.index_file, index)

        # Update reinforcements with new learnings
        self._register_learnings(learnings)

        return block

    def _register_learnings(self, learnings: list[Learning]) -> None:
        """Register new learnings in the reinforcements file."""
        reinforcements = self._read_json(self.reinforcements_file)

        for learning in learnings:
            reinforcements["learnings"][learning.id] = {
                "category": learning.category.value,
                "confidence": learning.confidence,
                "outcome_count": len(learning.outcomes),
                "last_updated": datetime.utcnow().isoformat(),
            }

        self._write_json(self.reinforcements_file, reinforcements)

        # Also index learnings for full-text search
        self._index_learnings(learnings)

    def _get_search_index(self) -> "SearchIndex":
        """Get or create the search index for this ledger.

        Returns:
            SearchIndex instance for this ledger's cache directory
        """
        if self._search_index is None:
            from ..search import SearchIndex

            cache_dir = self.path.parent / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            self._search_index = SearchIndex(cache_dir / "search.db")

        return self._search_index

    def _index_learnings(self, learnings: list[Learning]) -> None:
        """Add learnings to the search index.

        Args:
            learnings: List of learnings to index
        """
        try:
            index = self._get_search_index()
            for learning in learnings:
                index.index_learning(
                    learning_id=learning.id,
                    category=learning.category.value,
                    content=learning.content,
                    confidence=learning.confidence,
                    source=learning.source,
                )
        except Exception:
            # Don't fail block creation if indexing fails
            pass

    def search_learnings(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 20,
    ) -> list["SearchResult"]:
        """Search learnings using full-text search.

        Args:
            query: The search query (supports FTS5 query syntax)
            category: Optional category filter (discovery, decision, error, pattern)
            limit: Maximum number of results to return

        Returns:
            List of SearchResult objects sorted by relevance
        """
        index = self._get_search_index()

        if category:
            return index.search_by_category(query, category, limit=limit)
        else:
            return index.search(query, limit=limit)

    def reindex_search(self) -> int:
        """Rebuild the search index from the ledger.

        Returns:
            Number of learnings indexed
        """
        index = self._get_search_index()
        return index.reindex_ledger(self)

    def update_learning_confidence(self, learning_id: str, new_confidence: float) -> None:
        """Update the confidence of a learning after an outcome."""
        reinforcements = self._read_json(self.reinforcements_file)

        if learning_id in reinforcements["learnings"]:
            reinforcements["learnings"][learning_id]["confidence"] = new_confidence
            reinforcements["learnings"][learning_id]["last_updated"] = datetime.utcnow().isoformat()
            reinforcements["learnings"][learning_id]["outcome_count"] += 1
            self._write_json(self.reinforcements_file, reinforcements)

    def get_learnings_by_confidence(
        self,
        min_confidence: float = 0.0,
        category: Optional[LearningCategory] = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get learnings sorted by confidence.

        Args:
            min_confidence: Minimum confidence threshold
            category: Filter by category
            limit: Maximum number of results

        Returns:
            List of learning summaries with confidence scores
        """
        reinforcements = self._read_json(self.reinforcements_file)
        learnings = reinforcements.get("learnings", {})

        results = []
        for learning_id, data in learnings.items():
            if data["confidence"] < min_confidence:
                continue
            if category and data["category"] != category.value:
                continue
            results.append({
                "id": learning_id,
                **data,
            })

        # Sort by confidence descending
        results.sort(key=lambda x: x["confidence"], reverse=True)
        return results[:limit]

    def get_all_blocks(self) -> list[Block]:
        """Retrieve all blocks in chain order (oldest first)."""
        index = self._read_json(self.index_file)
        blocks = []

        for block_info in index.get("blocks", []):
            block = self.get_block(block_info["id"])
            if block:
                blocks.append(block)

        return blocks

    def verify_chain(self) -> tuple[bool, list[str]]:
        """Verify the integrity of the chain.

        Returns:
            Tuple of (is_valid, list of error messages)
        """
        index = self._read_json(self.index_file)
        errors = []

        prev_id = None
        for block_info in index.get("blocks", []):
            block = self.get_block(block_info["id"])

            if not block:
                errors.append(f"Block {block_info['id']} not found on disk")
                continue

            if block.hash != block_info["hash"]:
                errors.append(f"Block {block.id} hash mismatch (tampering detected)")

            if block.parent_block != prev_id:
                errors.append(f"Block {block.id} has incorrect parent reference")

            prev_id = block.id

        return len(errors) == 0, errors

    def import_from_global(self, global_ledger: "Ledger", learning_ids: list[str]) -> None:
        """Import specific learnings from the global ledger.

        Args:
            global_ledger: The global ledger to import from
            learning_ids: IDs of learnings to import
        """
        if self.is_global:
            raise ValueError("Cannot import into global ledger")

        imports = self._read_json(self.imports_file)

        for learning_id in learning_ids:
            if learning_id not in imports["imports"]:
                imports["imports"].append(learning_id)

        self._write_json(self.imports_file, imports)

    def promote_to_global(
        self,
        global_ledger: "Ledger",
        confidence_threshold: float = 0.8,
    ) -> list[str]:
        """Promote high-confidence learnings to the global ledger.

        Args:
            global_ledger: The global ledger to promote to
            confidence_threshold: Minimum confidence to promote

        Returns:
            List of promoted learning IDs
        """
        if self.is_global:
            raise ValueError("Cannot promote from global ledger")

        high_confidence = self.get_learnings_by_confidence(min_confidence=confidence_threshold)
        promoted = []

        for learning_info in high_confidence:
            # Find the actual learning object
            for block in self.get_all_blocks():
                for learning in block.learnings:
                    if learning.id == learning_info["id"]:
                        # Check if already in global
                        global_reinforcements = global_ledger._read_json(
                            global_ledger.reinforcements_file
                        )
                        if learning.id not in global_reinforcements.get("learnings", {}):
                            global_ledger.append_block(
                                session_id="promotion",
                                learnings=[learning],
                            )
                            promoted.append(learning.id)
                        break

        return promoted
