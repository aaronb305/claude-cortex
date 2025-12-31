"""Ledger chain management for storing and retrieving blocks."""

from __future__ import annotations

import fcntl
import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING, Generator

from .models import Block, Learning, LearningCategory, OutcomeResult, compute_content_hash
from .merkle import MerkleTree
from .objects import ObjectStore

if TYPE_CHECKING:
    from ..search import SearchIndex
    from ..search.index import SearchResult
    from .crypto import KeyManager, VerifyResult

logger = logging.getLogger("continuous_claude.ledger")


@contextmanager
def file_lock(path: Path, exclusive: bool = True) -> Generator[None, None, None]:
    """Context manager for file locking using fcntl.flock().

    Args:
        path: Path to the file to lock (creates a .lock file alongside)
        exclusive: If True, acquire exclusive lock. If False, acquire shared lock.

    Yields:
        None when lock is acquired
    """
    lock_path = path.parent / f".{path.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH

    with open(lock_path, 'w') as lock_file:
        try:
            fcntl.flock(lock_file.fileno(), lock_type)
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


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
        self.failed_indexing_file = path / "failed_indexing.json"
        self.merkle_file = path / "merkle.json"

        # Search index is lazily initialized
        self._search_index: Optional["SearchIndex"] = None

        # Merkle tree is lazily initialized
        self._merkle_tree: Optional[MerkleTree] = None

        # Object store is lazily initialized
        self._object_store: Optional[ObjectStore] = None

        # Key manager is lazily initialized
        self._key_manager: Optional["KeyManager"] = None

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

    @property
    def object_store(self) -> ObjectStore:
        """Get or create the object store for this ledger.

        Returns:
            ObjectStore instance for this ledger
        """
        if self._object_store is None:
            self._object_store = ObjectStore(self.path)
        return self._object_store

    @property
    def key_manager(self) -> "KeyManager":
        """Get or create the key manager for this ledger.

        Returns:
            KeyManager instance for this ledger
        """
        if self._key_manager is None:
            from .crypto import KeyManager
            self._key_manager = KeyManager(self.path)
        return self._key_manager

    def _read_json(self, path: Path) -> dict:
        """Read JSON from a file with shared lock."""
        with file_lock(path, exclusive=False):
            with open(path) as f:
                return json.load(f)

    def _write_json(self, path: Path, data: dict) -> None:
        """Write JSON to a file with exclusive lock."""
        with file_lock(path, exclusive=True):
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

    def append_block(
        self,
        session_id: str,
        learnings: list[Learning],
        deduplicate: bool = True,
        merge_duplicates: bool = True,
        sign: bool = True,
    ) -> Block:
        """Create and append a new block to the chain.

        Args:
            session_id: ID of the Claude session
            learnings: List of learnings to include in the block
            deduplicate: If True, filter out duplicate learnings before adding
            merge_duplicates: If True and deduplicate is True, boost confidence
                            of existing duplicates instead of just skipping
            sign: If True and an identity exists, sign the block

        Returns:
            The newly created block (may have fewer learnings if duplicates removed)
        """
        # Deduplicate learnings if requested
        if deduplicate and learnings:
            learnings, skipped = self.deduplicate_learnings(learnings, merge_duplicates)
            if not learnings:
                # All learnings were duplicates - create empty block marker
                # or return early if no new knowledge
                pass  # Continue to create block with empty learnings for session tracking

        # Lock index file for the entire operation to ensure atomicity
        # All operations must succeed or rollback to prevent orphan blocks
        with file_lock(self.index_file, exclusive=True):
            # Read index within lock context
            with open(self.index_file) as f:
                index = json.load(f)
            head = index.get("head")

            block = Block(
                session_id=session_id,
                parent_block=head,
                learnings=learnings,
            )

            # Sign the block if requested and identity exists
            if sign and self.key_manager.has_identity():
                sig_result = self.key_manager.sign_block_hash(block.hash)
                if sig_result:
                    key_id, signature = sig_result
                    block.author_key_id = key_id
                    block.signature = signature

            # Write block to file directly - new block files are unique,
            # no contention risk since block ID is a UUID
            block_file = self.blocks_dir / f"{block.id}.json"
            with open(block_file, "w") as f:
                json.dump(block.model_dump(mode="json"), f, indent=2, default=str)

            try:
                # Update index atomically within the same lock context
                index["head"] = block.id
                index["blocks"].append({
                    "id": block.id,
                    "timestamp": block.timestamp.isoformat(),
                    "hash": block.hash,
                    "parent": head,
                })
                with open(self.index_file, "w") as f:
                    json.dump(index, f, indent=2, default=str)

                # Register learnings inside lock context to ensure atomicity
                # If this fails, we rollback by deleting the block file
                if learnings:
                    self._register_learnings_internal(learnings, block.id)

            except Exception:
                # Rollback: delete the block file if index update or registration failed
                if block_file.exists():
                    block_file.unlink()
                raise

        # Update Merkle tree after successful block append (outside lock)
        self.update_merkle_tree()

        return block

    def _register_learnings(self, learnings: list[Learning], block_id: str) -> None:
        """Register new learnings in the reinforcements file.

        This method acquires its own lock on reinforcements.json.
        For use within an existing lock context, use _register_learnings_internal.

        Args:
            learnings: List of learnings to register
            block_id: ID of the block containing these learnings
        """
        with file_lock(self.reinforcements_file, exclusive=True):
            self._register_learnings_internal(learnings, block_id)

    def _register_learnings_internal(self, learnings: list[Learning], block_id: str) -> None:
        """Register new learnings in the reinforcements file (no locking).

        This is the internal implementation that does not acquire a lock.
        Called from append_block where we already hold the index lock, and
        from _register_learnings which provides its own locking.

        Also stores learning content in the ObjectStore for content-addressed
        storage and deduplication.

        Args:
            learnings: List of learnings to register
            block_id: ID of the block containing these learnings
        """
        # Read current reinforcements
        if self.reinforcements_file.exists():
            with open(self.reinforcements_file) as f:
                reinforcements = json.load(f)
        else:
            reinforcements = {"learnings": {}}

        for learning in learnings:
            # Store in object store first - returns the 16-char content hash
            object_store_hash = self.object_store.store_learning(learning)

            # Ensure content_hash is computed (16-char version for dedup)
            content_hash = learning.content_hash
            if content_hash is None:
                content_hash = compute_content_hash(learning.content)

            reinforcements["learnings"][learning.id] = {
                "category": learning.category.value,
                "content": learning.content,  # Keep for backwards compat
                "confidence": learning.confidence,
                "outcome_count": len(learning.outcomes),
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "last_applied": datetime.now(timezone.utc).isoformat(),
                "block_id": block_id,
                "content_hash": content_hash,
                "object_store_hash": object_store_hash,  # Link to object store
                "outcomes": [],  # Initialize empty outcomes list
            }

        with open(self.reinforcements_file, "w") as f:
            json.dump(reinforcements, f, indent=2, default=str)

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

        Uses batch commits for better performance when adding multiple learnings.
        Tracks failures for later retry.

        Args:
            learnings: List of learnings to index
        """
        failed_ids: list[str] = []
        try:
            index = self._get_search_index()
            for learning in learnings:
                try:
                    index.index_learning(
                        learning_id=learning.id,
                        category=learning.category.value,
                        content=learning.content,
                        confidence=learning.confidence,
                        source=learning.source,
                        commit=False,  # Batch operation
                    )
                except Exception as e:
                    logger.warning(f"Failed to index learning {learning.id}: {e}")
                    failed_ids.append(learning.id)
            # Single commit at the end
            index.connection.commit()
        except Exception as e:
            logger.error(f"Search index operation failed: {e}")
            # Complete failure - all learnings failed
            failed_ids = [l.id for l in learnings]

        # Track any failures for later retry
        if failed_ids:
            logger.info(f"Tracking {len(failed_ids)} failed indexing operations")
            self._track_failed_indexing(failed_ids)

    def _track_failed_indexing(self, learning_ids: list[str]) -> None:
        """Track learning IDs that failed to index for later retry.

        Args:
            learning_ids: List of learning IDs that failed to index
        """
        with file_lock(self.failed_indexing_file, exclusive=True):
            # Read existing failures
            if self.failed_indexing_file.exists():
                with open(self.failed_indexing_file) as f:
                    data = json.load(f)
            else:
                data = {"failed": [], "last_updated": None}

            # Add new failures (avoid duplicates)
            existing = set(data.get("failed", []))
            for lid in learning_ids:
                if lid not in existing:
                    data["failed"].append(lid)
                    existing.add(lid)

            data["last_updated"] = datetime.now(timezone.utc).isoformat()

            # Write back
            with open(self.failed_indexing_file, "w") as f:
                json.dump(data, f, indent=2)

    def _retry_failed_indexing(self) -> tuple[int, int]:
        """Retry indexing for learnings that previously failed.

        Returns:
            Tuple of (success_count, remaining_failures)
        """
        if not self.failed_indexing_file.exists():
            return 0, 0

        with file_lock(self.failed_indexing_file, exclusive=True):
            with open(self.failed_indexing_file) as f:
                data = json.load(f)

            failed_ids = data.get("failed", [])
            if not failed_ids:
                return 0, 0

            success_count = 0
            still_failed: list[str] = []

            try:
                index = self._get_search_index()

                for learning_id in failed_ids:
                    learning, _ = self.get_learning_by_id(learning_id, prefix_match=False)
                    if not learning:
                        # Learning no longer exists, remove from failures
                        continue

                    try:
                        index.index_learning(
                            learning_id=learning.id,
                            category=learning.category.value,
                            content=learning.content,
                            confidence=learning.confidence,
                            source=learning.source,
                            commit=False,
                        )
                        success_count += 1
                    except Exception:
                        still_failed.append(learning_id)

                # Commit all successful indexing
                index.connection.commit()
            except Exception:
                # Complete failure - all remain failed
                still_failed = failed_ids

            # Update the failed indexing file
            data["failed"] = still_failed
            data["last_updated"] = datetime.now(timezone.utc).isoformat()
            data["last_retry"] = datetime.now(timezone.utc).isoformat()

            with open(self.failed_indexing_file, "w") as f:
                json.dump(data, f, indent=2)

        return success_count, len(still_failed)

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

    def get_learning_by_id(
        self,
        learning_id: str,
        prefix_match: bool = True,
    ) -> tuple[Optional[Learning], Optional[Block]]:
        """Look up a learning by ID efficiently using reinforcements.json.

        Uses the block_id stored in reinforcements to directly load the
        relevant block instead of scanning all blocks.

        Args:
            learning_id: Full learning ID or prefix to match
            prefix_match: If True, match by prefix; if False, require exact match

        Returns:
            Tuple of (Learning, Block) if found, (None, None) otherwise
        """
        reinforcements = self._read_json(self.reinforcements_file)
        learnings_data = reinforcements.get("learnings", {})

        # Find matching learning ID
        matched_id = None
        block_id = None

        if prefix_match:
            matches = [(lid, data) for lid, data in learnings_data.items()
                       if lid.startswith(learning_id)]
            if len(matches) == 0:
                return None, None
            if len(matches) > 1:
                # Ambiguous prefix - return None to indicate multiple matches
                # Caller should provide a longer prefix or full ID
                return None, None
            matched_id, data = matches[0]
            block_id = data.get("block_id")
        else:
            if learning_id in learnings_data:
                matched_id = learning_id
                block_id = learnings_data[learning_id].get("block_id")

        if not matched_id:
            return None, None

        # If block_id is available, load only that block
        if block_id:
            block = self.get_block(block_id)
            if block:
                for learning in block.learnings:
                    if learning.id == matched_id:
                        return learning, block

        # Fallback: scan all blocks (for backward compatibility with old data)
        for block in self.get_all_blocks():
            for learning in block.learnings:
                if learning.id == matched_id:
                    return learning, block

        return None, None

    def get_learning_by_content_hash(self, content_hash: str) -> Optional[dict]:
        """Get full learning data from object store by content hash.

        This provides O(1) access to learning content via the object store.
        Falls back through multiple sources for backwards compatibility:
        1. ObjectStore (new learnings)
        2. reinforcements.json cache (existing learnings)
        3. Block scan (oldest learnings without object_store_hash)

        Args:
            content_hash: The 16-char content hash to look up

        Returns:
            Dict with learning data if found, None otherwise.
            Includes: content, category, source, confidence, etc.
        """
        # Try object store first (get_learning_data returns full dict)
        obj_data = self.object_store.get_learning_data(content_hash)
        if obj_data:
            return obj_data

        # Search reinforcements for matching content_hash
        reinforcements = self._read_json(self.reinforcements_file)
        learnings_data = reinforcements.get("learnings", {})

        for learning_id, data in learnings_data.items():
            if data.get("content_hash") == content_hash:
                # Check if we have an object_store_hash
                obj_hash = data.get("object_store_hash")
                if obj_hash:
                    obj_data = self.object_store.get_learning_data(obj_hash)
                    if obj_data:
                        return obj_data

                # Fall back to reinforcements.json cache
                return {
                    "content": data.get("content"),
                    "category": data.get("category"),
                    "content_hash": content_hash,
                    "confidence": data.get("confidence"),
                    "source": None,  # Not stored in reinforcements
                    "learning_id": learning_id,
                }

        # Final fallback: scan blocks for content (very slow, backwards compat only)
        for block in self.get_all_blocks():
            for learning in block.learnings:
                if learning.content_hash == content_hash:
                    return {
                        "content": learning.content,
                        "category": learning.category.value,
                        "content_hash": content_hash,
                        "confidence": learning.confidence,
                        "source": learning.source,
                        "learning_id": learning.id,
                    }

        return None

    def get_learning_content(self, learning_id: str) -> Optional[str]:
        """Get the content string for a learning by ID.

        Uses multiple lookup strategies for efficiency and backwards compatibility:
        1. ObjectStore via object_store_hash (fastest for new learnings)
        2. reinforcements.json cache (fast, works for all learnings)
        3. Block scan (slowest, backwards compat)

        Args:
            learning_id: ID of the learning (can be prefix)

        Returns:
            The learning content string, or None if not found
        """
        reinforcements = self._read_json(self.reinforcements_file)
        learnings_data = reinforcements.get("learnings", {})

        # Find matching learning
        matched_data = None
        for lid, data in learnings_data.items():
            if lid.startswith(learning_id):
                matched_data = data
                break

        if not matched_data:
            # Fall back to block scan
            learning, _ = self.get_learning_by_id(learning_id)
            return learning.content if learning else None

        # Try object store first (get() returns content string directly)
        obj_hash = matched_data.get("object_store_hash")
        if obj_hash:
            content = self.object_store.get(obj_hash)
            if content is not None:
                return content

        # Fall back to reinforcements cache
        return matched_data.get("content")

    def record_outcome(
        self,
        learning_id: str,
        result: OutcomeResult,
        context: str,
    ) -> tuple[bool, float, str]:
        """Record an outcome for a learning without modifying block files.

        Outcomes are stored in reinforcements.json to preserve block immutability.
        The confidence is adjusted based on the outcome result.

        Args:
            learning_id: ID of the learning (can be a prefix)
            result: The outcome result (success, failure, partial)
            context: Description of how the knowledge was applied

        Returns:
            Tuple of (success, new_confidence, matched_id). If learning not found,
            returns (False, 0.0, "")
        """
        # Confidence adjustment deltas
        delta_map = {
            OutcomeResult.SUCCESS: 0.1,
            OutcomeResult.PARTIAL: 0.02,
            OutcomeResult.FAILURE: -0.15,
        }
        delta = delta_map[result]

        with file_lock(self.reinforcements_file, exclusive=True):
            with open(self.reinforcements_file) as f:
                reinforcements = json.load(f)

            learnings_data = reinforcements.get("learnings", {})

            # Find the learning by ID or prefix
            matched_id = None
            for lid in learnings_data.keys():
                if lid.startswith(learning_id):
                    matched_id = lid
                    break

            if not matched_id:
                return False, 0.0, ""

            learning_entry = learnings_data[matched_id]

            # Calculate new confidence with bounds
            old_confidence = learning_entry.get("confidence", 0.5)
            new_confidence = max(0.0, min(1.0, old_confidence + delta))

            # Create outcome record
            outcome_record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "result": result.value,
                "context": context,
                "delta": delta,
            }

            # Update the learning entry
            learning_entry["confidence"] = new_confidence
            learning_entry["last_updated"] = datetime.now(timezone.utc).isoformat()
            learning_entry["last_applied"] = datetime.now(timezone.utc).isoformat()
            learning_entry["outcome_count"] = learning_entry.get("outcome_count", 0) + 1

            # Initialize outcomes list if not present
            if "outcomes" not in learning_entry:
                learning_entry["outcomes"] = []
            learning_entry["outcomes"].append(outcome_record)

            # Write back
            with open(self.reinforcements_file, "w") as f:
                json.dump(reinforcements, f, indent=2, default=str)

        return True, new_confidence, matched_id

    def get_learning_outcomes(self, learning_id: str) -> list[dict]:
        """Get the outcome history for a learning from reinforcements.json.

        Args:
            learning_id: ID of the learning (can be a prefix)

        Returns:
            List of outcome records, empty if learning not found
        """
        reinforcements = self._read_json(self.reinforcements_file)
        learnings_data = reinforcements.get("learnings", {})

        # Find the learning by ID or prefix
        for lid, data in learnings_data.items():
            if lid.startswith(learning_id):
                return data.get("outcomes", [])

        return []

    def find_by_content_hash(self, content_hash: str) -> tuple[Optional[Learning], Optional[str]]:
        """Find a learning by its content hash for deduplication.

        Uses the content_hash stored in reinforcements.json for O(n) lookup
        where n is the number of learnings (not blocks).

        Args:
            content_hash: The 16-character content hash to search for

        Returns:
            Tuple of (Learning, learning_id) if found, (None, None) otherwise
        """
        reinforcements = self._read_json(self.reinforcements_file)
        learnings_data = reinforcements.get("learnings", {})

        # Search for matching content_hash in reinforcements
        for learning_id, data in learnings_data.items():
            if data.get("content_hash") == content_hash:
                # Found a match, retrieve the full learning
                learning, _ = self.get_learning_by_id(learning_id, prefix_match=False)
                if learning:
                    return learning, learning_id

        return None, None

    def deduplicate_learnings(
        self,
        learnings: list[Learning],
        merge_duplicates: bool = True,
    ) -> tuple[list[Learning], list[str]]:
        """Filter out duplicate learnings and optionally merge with existing.

        For each learning, checks if a learning with the same content_hash
        already exists in the ledger. If so, either skips it or merges by
        boosting the existing learning's confidence.

        This method is optimized to read reinforcements.json once at the start
        and write once at the end, avoiding O(n*m) file operations.

        Args:
            learnings: List of learnings to deduplicate
            merge_duplicates: If True, boost confidence of existing duplicate.
                            If False, simply skip duplicates.

        Returns:
            Tuple of (unique_learnings, skipped_ids) where:
            - unique_learnings: Learnings that should be added
            - skipped_ids: IDs of existing learnings that were duplicates
        """
        unique = []
        skipped = []

        # Use exclusive lock for the entire read-modify-write operation
        with file_lock(self.reinforcements_file, exclusive=True):
            with open(self.reinforcements_file) as f:
                reinforcements = json.load(f)
            learnings_data = reinforcements.get("learnings", {})

            # Build content_hash -> learning_id lookup for O(1) duplicate detection
            hash_to_id: dict[str, str] = {}
            for learning_id, data in learnings_data.items():
                content_hash = data.get("content_hash")
                if content_hash:
                    hash_to_id[content_hash] = learning_id

            # Track whether we need to write back reinforcements
            reinforcements_modified = False

            for learning in learnings:
                # Ensure content_hash is computed
                if learning.content_hash is None:
                    learning.content_hash = compute_content_hash(learning.content)

                # Check for existing duplicate using the lookup table
                existing_id = hash_to_id.get(learning.content_hash)

                if existing_id:
                    skipped.append(existing_id)

                    if merge_duplicates and existing_id in learnings_data:
                        # Boost confidence of existing learning (discovery reinforcement)
                        current_conf = learnings_data[existing_id]["confidence"]
                        # Apply a small boost (0.05) capped at 1.0
                        new_conf = min(1.0, current_conf + 0.05)
                        learnings_data[existing_id]["confidence"] = new_conf
                        learnings_data[existing_id]["last_updated"] = datetime.now(timezone.utc).isoformat()
                        learnings_data[existing_id]["rediscovery_count"] = (
                            learnings_data[existing_id].get("rediscovery_count", 0) + 1
                        )
                        reinforcements_modified = True
                else:
                    unique.append(learning)

            # Write back reinforcements once if any duplicates were merged
            if reinforcements_modified:
                with open(self.reinforcements_file, "w") as f:
                    json.dump(reinforcements, f, indent=2, default=str)

        return unique, skipped

    def update_learning_confidence(self, learning_id: str, new_confidence: float) -> None:
        """Update the confidence of a learning after an outcome.

        Note: Prefer using record_outcome() which handles confidence updates
        automatically. This method is kept for backward compatibility.
        """
        with file_lock(self.reinforcements_file, exclusive=True):
            with open(self.reinforcements_file) as f:
                reinforcements = json.load(f)

            if learning_id in reinforcements["learnings"]:
                reinforcements["learnings"][learning_id]["confidence"] = new_confidence
                reinforcements["learnings"][learning_id]["last_updated"] = datetime.now(timezone.utc).isoformat()
                reinforcements["learnings"][learning_id]["last_applied"] = datetime.now(timezone.utc).isoformat()
                reinforcements["learnings"][learning_id]["outcome_count"] = \
                    reinforcements["learnings"][learning_id].get("outcome_count", 0) + 1

                with open(self.reinforcements_file, "w") as f:
                    json.dump(reinforcements, f, indent=2, default=str)

    def get_effective_confidence(self, learning_id: str) -> float:
        """Calculate effective confidence with time-based decay.

        Learnings that haven't been applied recently decay in confidence.
        The decay uses a 180-day (6-month) half-life, with a minimum floor
        of 50% of the stored confidence.

        Formula: effective = base_confidence * decay_factor
        decay_factor = max(0.5, 1.0 - (days_since_applied / 180))

        Args:
            learning_id: ID of the learning to calculate effective confidence for

        Returns:
            The effective confidence after applying decay
        """
        reinforcements = self._read_json(self.reinforcements_file)
        learning_data = reinforcements.get("learnings", {}).get(learning_id)

        if not learning_data:
            return 0.0

        base_confidence = learning_data.get("confidence", 0.5)

        # Get the last_applied timestamp, falling back to last_updated or created_at
        last_applied_str = learning_data.get("last_applied") or learning_data.get("last_updated")

        if not last_applied_str:
            # No timestamp available, return base confidence (no decay for unknown age)
            return base_confidence

        try:
            last_applied = datetime.fromisoformat(last_applied_str)
            # Ensure timezone-aware for comparison
            if last_applied.tzinfo is None:
                last_applied = last_applied.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return base_confidence

        # Calculate days since last applied
        days_since_applied = (datetime.now(timezone.utc) - last_applied).days

        # Exponential decay with 180-day half-life and 0.5 minimum floor
        # At 180 days: 50%, at 360 days: 25%, etc.
        decay_factor = max(0.5, 0.5 ** (days_since_applied / 180.0))

        return base_confidence * decay_factor

    def touch_learning(self, learning_id: str) -> bool:
        """Update the last_applied timestamp when a learning is referenced.

        This resets the decay clock for the learning, maintaining its
        effective confidence at the stored level.

        Note: Only updates reinforcements.json to preserve block immutability.
        Block files are never modified after creation to maintain hash integrity.

        Args:
            learning_id: ID of the learning to touch

        Returns:
            True if the learning was found and updated, False otherwise
        """
        with file_lock(self.reinforcements_file, exclusive=True):
            with open(self.reinforcements_file) as f:
                reinforcements = json.load(f)

            if learning_id not in reinforcements.get("learnings", {}):
                return False

            reinforcements["learnings"][learning_id]["last_applied"] = datetime.now(timezone.utc).isoformat()

            with open(self.reinforcements_file, "w") as f:
                json.dump(reinforcements, f, indent=2, default=str)

        return True

    def _compute_effective_confidence_from_data(
        self,
        learning_data: dict,
    ) -> float:
        """Calculate effective confidence from already-loaded learning data.

        Avoids re-reading reinforcements.json when we already have the data.

        Args:
            learning_data: The learning entry dict from reinforcements.json

        Returns:
            The effective confidence after applying decay
        """
        base_confidence = learning_data.get("confidence", 0.5)

        # Get the last_applied timestamp, falling back to last_updated
        last_applied_str = learning_data.get("last_applied") or learning_data.get("last_updated")

        if not last_applied_str:
            return base_confidence

        try:
            last_applied = datetime.fromisoformat(last_applied_str)
            if last_applied.tzinfo is None:
                last_applied = last_applied.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            return base_confidence

        days_since_applied = (datetime.now(timezone.utc) - last_applied).days
        # Exponential decay with 180-day half-life and 0.5 minimum floor
        # (same formula as get_effective_confidence)
        decay_factor = max(0.5, 0.5 ** (days_since_applied / 180.0))

        return base_confidence * decay_factor

    def get_learnings_by_confidence(
        self,
        min_confidence: float = 0.0,
        category: Optional[LearningCategory] = None,
        limit: int = 50,
        use_effective_confidence: bool = True,
    ) -> list[dict]:
        """Get learnings sorted by confidence.

        Args:
            min_confidence: Minimum confidence threshold (applied to effective confidence)
            category: Filter by category
            limit: Maximum number of results
            use_effective_confidence: If True, sort by effective (decayed) confidence

        Returns:
            List of learning summaries with confidence scores.
            Each dict includes both 'confidence' (stored) and 'effective_confidence' (decayed).
        """
        reinforcements = self._read_json(self.reinforcements_file)
        learnings = reinforcements.get("learnings", {})

        results = []
        for learning_id, data in learnings.items():
            # Calculate effective confidence inline to avoid re-reading reinforcements
            effective_conf = self._compute_effective_confidence_from_data(data)

            # Filter by effective confidence
            if effective_conf < min_confidence:
                continue
            if category and data["category"] != category.value:
                continue

            results.append({
                "id": learning_id,
                "effective_confidence": effective_conf,
                **data,
            })

        # Sort by effective confidence if enabled, otherwise by stored confidence
        sort_key = "effective_confidence" if use_effective_confidence else "confidence"
        results.sort(key=lambda x: x[sort_key], reverse=True)
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

    def verify_chain(
        self,
        verify_signatures: bool = False,
    ) -> tuple[bool, list[str]]:
        """Verify the integrity of the chain.

        Args:
            verify_signatures: If True, also verify block signatures

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

            # Optionally verify signature
            if verify_signatures:
                result = self.verify_block_signature(block.id)
                from .crypto import VerifyResult
                if result == VerifyResult.INVALID:
                    errors.append(f"Block {block.id} has invalid signature")
                elif result == VerifyResult.KEY_NOT_FOUND:
                    errors.append(f"Block {block.id} signed by unknown key {block.author_key_id}")
                elif result == VerifyResult.ERROR:
                    errors.append(f"Block {block.id} signature verification error")

            prev_id = block.id

        return len(errors) == 0, errors

    def verify_block_signature(self, block_id: str) -> "VerifyResult":
        """Verify a single block's signature.

        Args:
            block_id: ID of the block to verify

        Returns:
            VerifyResult indicating the verification outcome
        """
        from .crypto import VerifyResult

        block = self.get_block(block_id)
        if not block:
            return VerifyResult.ERROR

        if not block.signature or not block.author_key_id:
            return VerifyResult.NO_SIGNATURE

        return self.key_manager.verify_signature(
            block.hash,
            block.author_key_id,
            block.signature,
        )

    def verify_all_signatures(self) -> dict[str, "VerifyResult"]:
        """Verify signatures on all blocks.

        Returns:
            Dictionary mapping block_id to VerifyResult
        """
        from .crypto import VerifyResult

        results: dict[str, VerifyResult] = {}
        index = self._read_json(self.index_file)

        for block_info in index.get("blocks", []):
            block_id = block_info["id"]
            results[block_id] = self.verify_block_signature(block_id)

        return results

    def build_merkle_tree(self) -> MerkleTree:
        """Build a Merkle tree from all blocks in the ledger.

        Returns the tree and saves it to merkle.json.

        Returns:
            The built MerkleTree instance
        """
        index = self._read_json(self.index_file)
        blocks_info = index.get("blocks", [])

        # Create list of (block_id, block_hash) tuples for the MerkleTree
        leaves = [(b["id"], b["hash"]) for b in blocks_info]

        tree = MerkleTree(leaves)

        # Save to file
        with file_lock(self.merkle_file, exclusive=True):
            tree.save(self.merkle_file)

        # Update index with merkle_root
        self._update_merkle_root_in_index(tree.root_hash)

        # Cache the tree
        self._merkle_tree = tree

        return tree

    def get_merkle_root(self) -> Optional[str]:
        """Get the current Merkle root hash.

        Loads from merkle.json if available, otherwise builds tree.

        Returns:
            The Merkle root hash, or None if ledger is empty
        """
        # Check cached tree first
        if self._merkle_tree is not None:
            return self._merkle_tree.root_hash

        # Try to load from file
        if self.merkle_file.exists():
            with file_lock(self.merkle_file, exclusive=False):
                tree = MerkleTree.load(self.merkle_file)
                if tree:
                    self._merkle_tree = tree
                    return tree.root_hash

        # Build tree if not available
        tree = self.build_merkle_tree()
        return tree.root_hash

    def update_merkle_tree(self) -> None:
        """Update the Merkle tree after adding blocks.

        Called automatically after append_block().
        Invalidates the cached tree and rebuilds it.
        """
        # Invalidate cache
        self._merkle_tree = None

        # Rebuild the tree
        self.build_merkle_tree()

    def verify_merkle_tree(self) -> tuple[bool, list[str]]:
        """Verify the Merkle tree matches the actual blocks.

        Returns:
            Tuple of (valid, list of error messages)
        """
        errors: list[str] = []

        # Load the stored tree
        if not self.merkle_file.exists():
            # No merkle.json yet - this is okay for backwards compatibility
            # Build it now and return success
            self.build_merkle_tree()
            return True, []

        with file_lock(self.merkle_file, exclusive=False):
            stored_tree = MerkleTree.load(self.merkle_file)

        if not stored_tree:
            errors.append("Failed to load merkle.json")
            return False, errors

        # Get current block data from index and rebuild tree
        index = self._read_json(self.index_file)
        blocks_info = index.get("blocks", [])
        current_leaves = [(b["id"], b["hash"]) for b in blocks_info]
        current_tree = MerkleTree(current_leaves)

        # Check leaf count matches
        if len(stored_tree) != len(current_leaves):
            errors.append(
                f"Block count mismatch: tree has {len(stored_tree)}, "
                f"ledger has {len(current_leaves)}"
            )

        # Check root hashes match
        if stored_tree.root_hash != current_tree.root_hash:
            errors.append(
                f"Merkle root mismatch: stored {stored_tree.root_hash}, "
                f"computed {current_tree.root_hash}"
            )

        # Also verify the merkle_root in index matches
        stored_root = index.get("merkle_root")
        if stored_root and stored_root != stored_tree.root_hash:
            errors.append(
                f"Index merkle_root ({stored_root}) does not match "
                f"merkle.json root ({stored_tree.root_hash})"
            )

        return len(errors) == 0, errors

    def _update_merkle_root_in_index(self, merkle_root: Optional[str]) -> None:
        """Update the merkle_root field in index.json.

        Args:
            merkle_root: The new Merkle root hash
        """
        with file_lock(self.index_file, exclusive=True):
            with open(self.index_file) as f:
                index = json.load(f)

            index["merkle_root"] = merkle_root

            with open(self.index_file, "w") as f:
                json.dump(index, f, indent=2, default=str)

    def import_from_global(self, global_ledger: "Ledger", learning_ids: list[str]) -> None:
        """Import specific learnings from the global ledger.

        Args:
            global_ledger: The global ledger to import from
            learning_ids: IDs of learnings to import
        """
        if self.is_global:
            raise ValueError("Cannot import into global ledger")

        with file_lock(self.imports_file, exclusive=True):
            with open(self.imports_file) as f:
                imports = json.load(f)

            for learning_id in learning_ids:
                if learning_id not in imports["imports"]:
                    imports["imports"].append(learning_id)

            with open(self.imports_file, "w") as f:
                json.dump(imports, f, indent=2, default=str)

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
        if not high_confidence:
            return []

        # Build lookup dictionary in one pass: learning_id -> Learning object
        learning_lookup: dict[str, Learning] = {}
        for block in self.get_all_blocks():
            for learning in block.learnings:
                learning_lookup[learning.id] = learning

        # Get global reinforcements once for checking existing learnings
        global_reinforcements = global_ledger._read_json(
            global_ledger.reinforcements_file
        )
        existing_global_ids = set(global_reinforcements.get("learnings", {}).keys())

        promoted = []
        for learning_info in high_confidence:
            learning_id = learning_info["id"]
            learning = learning_lookup.get(learning_id)

            if learning and learning_id not in existing_global_ids:
                global_ledger.append_block(
                    session_id="promotion",
                    learnings=[learning],
                )
                promoted.append(learning_id)
                # Update existing_global_ids to prevent duplicate promotions
                existing_global_ids.add(learning_id)

                # Track promoted_to in source ledger's reinforcements
                self._track_promotion(learning_id, learning.id)

        return promoted

    def _track_promotion(self, source_id: str, promoted_id: str) -> None:
        """Track that a learning was promoted to another ledger.

        Args:
            source_id: ID of the learning in the source ledger
            promoted_id: ID of the learning in the target ledger
        """
        with file_lock(self.reinforcements_file, exclusive=True):
            with open(self.reinforcements_file) as f:
                reinforcements = json.load(f)

            if source_id in reinforcements.get("learnings", {}):
                if "promoted_to" not in reinforcements["learnings"][source_id]:
                    reinforcements["learnings"][source_id]["promoted_to"] = []
                if promoted_id not in reinforcements["learnings"][source_id]["promoted_to"]:
                    reinforcements["learnings"][source_id]["promoted_to"].append(promoted_id)
                reinforcements["learnings"][source_id]["promoted_at"] = datetime.now(timezone.utc).isoformat()

                with open(self.reinforcements_file, "w") as f:
                    json.dump(reinforcements, f, indent=2, default=str)

    def get_related_learnings(
        self,
        project_type: Optional[str] = None,
        keywords: Optional[list[str]] = None,
        tech_stack: Optional[list[str]] = None,
        min_confidence: float = 0.5,
        limit: int = 20,
    ) -> list[Learning]:
        """Get learnings related to a project type and keywords.

        Searches learnings based on:
        - Project type match (if learning has project_context)
        - Tech stack overlap
        - Keyword matching in content or project_context.keywords
        - Minimum confidence threshold

        Args:
            project_type: Type of project (python, node, rust, go, etc.)
            keywords: Keywords to match against content
            tech_stack: Technologies to match (fastapi, react, etc.)
            min_confidence: Minimum confidence threshold
            limit: Maximum results to return

        Returns:
            List of matching Learning objects sorted by relevance score
        """
        results: list[tuple[float, Learning]] = []

        # Normalize inputs
        project_type_lower = project_type.lower() if project_type else None
        keywords_lower = [k.lower() for k in keywords] if keywords else []
        tech_stack_lower = [t.lower() for t in tech_stack] if tech_stack else []

        # Get all learnings with sufficient confidence
        reinforcements = self._read_json(self.reinforcements_file)
        learnings_data = reinforcements.get("learnings", {})

        for learning_id, data in learnings_data.items():
            confidence = data.get("confidence", 0.5)
            if confidence < min_confidence:
                continue

            # Get actual learning object
            learning, _ = self.get_learning_by_id(learning_id, prefix_match=False)
            if not learning:
                continue

            # Calculate relevance score
            score = 0.0

            # Base score from confidence
            score += confidence * 0.5

            # Project type match
            if project_type_lower and learning.project_context:
                if learning.project_context.project_type:
                    if learning.project_context.project_type.lower() == project_type_lower:
                        score += 0.3

            # Tech stack overlap
            if tech_stack_lower and learning.project_context:
                ctx_stack = [t.lower() for t in learning.project_context.tech_stack]
                overlap = len(set(tech_stack_lower) & set(ctx_stack))
                if overlap > 0:
                    score += min(0.3, overlap * 0.1)

            # Keyword matching in content
            content_lower = learning.content.lower()
            keyword_matches = sum(1 for k in keywords_lower if k in content_lower)
            if keyword_matches > 0:
                score += min(0.4, keyword_matches * 0.1)

            # Keyword matching in project_context.keywords
            if learning.project_context and learning.project_context.keywords:
                ctx_keywords = [k.lower() for k in learning.project_context.keywords]
                ctx_matches = len(set(keywords_lower) & set(ctx_keywords))
                if ctx_matches > 0:
                    score += min(0.2, ctx_matches * 0.1)

            # Only include if there's some relevance beyond base confidence
            if score > confidence * 0.5:
                results.append((score, learning))

        # Sort by score descending
        results.sort(key=lambda x: x[0], reverse=True)

        return [learning for _, learning in results[:limit]]

    def import_learning(
        self,
        source_ledger: "Ledger",
        learning_id: str,
    ) -> Optional[Learning]:
        """Import a specific learning from another ledger.

        Creates a copy of the learning in this ledger with derived_from
        tracking the source.

        Args:
            source_ledger: The ledger to import from
            learning_id: ID of the learning to import

        Returns:
            The newly created learning, or None if not found or already exists
        """
        # Find the source learning
        source_learning, _ = source_ledger.get_learning_by_id(learning_id, prefix_match=True)
        if not source_learning:
            return None

        # Check if already imported (by content hash or derived_from)
        for block in self.get_all_blocks():
            for existing in block.learnings:
                if existing.content_hash == source_learning.content_hash:
                    return None  # Already exists
                if existing.derived_from == source_learning.id:
                    return None  # Already imported

        # Create a new learning derived from the source
        from uuid import uuid4
        new_learning = Learning(
            id=str(uuid4()),
            category=source_learning.category,
            content=source_learning.content,
            confidence=source_learning.confidence * 0.9,  # Slight discount for transfer
            source=source_learning.source,
            project_context=source_learning.project_context,
            derived_from=source_learning.id,
        )

        # Append to a new block
        self.append_block(
            session_id="import",
            learnings=[new_learning],
            deduplicate=False,  # Already checked for duplicates above
        )

        # Track the import in the source ledger's reinforcements
        source_ledger._track_promotion(source_learning.id, new_learning.id)

        return new_learning
