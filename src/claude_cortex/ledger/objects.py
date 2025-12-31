"""Content-addressed object store for learnings."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, TYPE_CHECKING
from uuid import uuid4

from .models import compute_content_hash

if TYPE_CHECKING:
    from .models import Learning


class ObjectStore:
    """
    Content-addressed storage for learnings.

    Objects are stored by their content hash in a sharded directory structure:
    objects/
      ab/
        ab12cd34.json  # 16-char hash as filename
      cd/
        cd56ef78.json

    This enables:
    - Automatic deduplication (same content = same hash)
    - Efficient content lookup by hash
    - Cross-ledger content sharing

    The store supports two modes:
    - Simple mode: store(content: str) returns hash, get(hash) returns content
    - Rich mode: store_learning(learning) stores metadata, get_learning_data returns full dict
    """

    def __init__(self, ledger_path: Path):
        """Initialize object store at ledger_path (objects stored in ledger_path/)"""
        # Note: ledger_path IS the objects directory, not a parent
        self.path = ledger_path
        self.path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def compute_content_hash(content: str) -> str:
        """Compute content hash (static method wrapper for backwards compat)."""
        return compute_content_hash(content)

    def _get_object_path(self, content_hash: str) -> Path:
        """Get path for an object: objects/ab/ab12cd34.json"""
        prefix = content_hash[:2]
        return self.path / prefix / f"{content_hash}.json"

    def store(self, content: str) -> str:
        """
        Store content in the object store.

        Returns the content hash (16-char). If content already exists,
        returns existing hash (deduplication).

        Args:
            content: String content to store

        Returns:
            16-character content hash
        """
        content_hash = compute_content_hash(content)
        object_path = self._get_object_path(content_hash)

        # If object already exists, just return the hash (deduplication)
        if object_path.exists():
            return content_hash

        # Create the shard directory if needed
        object_path.parent.mkdir(parents=True, exist_ok=True)

        # Build the object data (simple mode - just content)
        object_data = {
            "content": content,
            "content_hash": content_hash,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }

        # Write atomically by writing to temp file then renaming
        # Use UUID in temp file name to prevent race conditions with concurrent writes
        temp_path = object_path.with_suffix(f".{uuid4().hex[:8]}.tmp")
        try:
            with open(temp_path, "w") as f:
                json.dump(object_data, f, indent=2)
            temp_path.rename(object_path)
        except Exception:
            # Clean up temp file on failure
            if temp_path.exists():
                temp_path.unlink()
            raise

        return content_hash

    def store_learning(self, learning: "Learning") -> str:
        """
        Store a Learning object with full metadata.

        Returns the content hash. If content already exists, returns existing
        hash but metadata is NOT updated (content-addressed = immutable).

        Args:
            learning: Learning object to store

        Returns:
            16-character content hash
        """
        content_hash = compute_content_hash(learning.content)
        object_path = self._get_object_path(content_hash)

        # If object already exists, just return the hash (deduplication)
        if object_path.exists():
            return content_hash

        # Create the shard directory if needed
        object_path.parent.mkdir(parents=True, exist_ok=True)

        # Build the object data (rich mode - full learning data)
        object_data = {
            "type": "learning",
            "content_hash": content_hash,
            "category": learning.category.value,
            "content": learning.content,
            "confidence": learning.confidence,
            "source": learning.source,
            "first_seen": learning.created_at.isoformat() if learning.created_at else datetime.now(timezone.utc).isoformat(),
            "project_context": learning.project_context.model_dump() if learning.project_context else None,
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }

        # Write atomically by writing to temp file then renaming
        # Use UUID in temp file name to prevent race conditions with concurrent writes
        temp_path = object_path.with_suffix(f".{uuid4().hex[:8]}.tmp")
        try:
            with open(temp_path, "w") as f:
                json.dump(object_data, f, indent=2)
            temp_path.rename(object_path)
        except Exception:
            # Clean up temp file on failure
            if temp_path.exists():
                temp_path.unlink()
            raise

        return content_hash

    def get(self, content_hash: str) -> Optional[str]:
        """
        Retrieve content by its hash.

        Args:
            content_hash: 16-character content hash

        Returns:
            The content string, or None if not found
        """
        object_path = self._get_object_path(content_hash)

        if not object_path.exists():
            return None

        try:
            with open(object_path) as f:
                data = json.load(f)
                return data.get("content")
        except (json.JSONDecodeError, OSError):
            return None

    def get_learning_data(self, content_hash: str) -> Optional[dict]:
        """
        Retrieve full learning data by its hash.

        Args:
            content_hash: 16-character content hash

        Returns:
            Dict with full learning data, or None if not found
        """
        object_path = self._get_object_path(content_hash)

        if not object_path.exists():
            return None

        try:
            with open(object_path) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def exists(self, content_hash: str) -> bool:
        """Check if an object with this hash exists."""
        return self._get_object_path(content_hash).exists()

    def list_all(self) -> list[str]:
        """List all content hashes in the store."""
        hashes = []

        # Iterate through shard directories
        if not self.path.exists():
            return hashes

        for shard_dir in self.path.iterdir():
            if shard_dir.is_dir() and len(shard_dir.name) == 2:
                for obj_file in shard_dir.iterdir():
                    if obj_file.is_file() and obj_file.suffix == ".json":
                        # Extract hash from filename (remove .json suffix)
                        content_hash = obj_file.stem
                        # Validate that filename looks like a 16-char hash
                        if len(content_hash) == 16:
                            hashes.append(content_hash)

        return sorted(hashes)

    def delete(self, content_hash: str) -> bool:
        """Delete an object. Returns True if deleted, False if not found."""
        object_path = self._get_object_path(content_hash)

        if not object_path.exists():
            return False

        object_path.unlink()

        # Clean up empty shard directory
        shard_dir = object_path.parent
        try:
            if shard_dir.exists() and not any(shard_dir.iterdir()):
                shard_dir.rmdir()
        except OSError:
            # Ignore errors cleaning up directories
            pass

        return True

    def gc(self, referenced_hashes: set[str]) -> int:
        """
        Garbage collect unreferenced objects.
        Returns count of deleted objects.
        """
        deleted_count = 0
        all_hashes = self.list_all()

        for content_hash in all_hashes:
            if content_hash not in referenced_hashes:
                if self.delete(content_hash):
                    deleted_count += 1

        return deleted_count

    def verify_integrity(self, content_hash: str) -> bool:
        """
        Verify that an object's stored hash matches its actual content.
        Returns True if valid, False if corrupted or not found.
        """
        content = self.get(content_hash)
        if content is None:
            return False

        actual_hash = compute_content_hash(content)
        return actual_hash == content_hash

    def verify_all(self) -> tuple[int, list[str]]:
        """
        Verify integrity of all objects in the store.
        Returns (valid_count, list of corrupted hashes).
        """
        valid_count = 0
        corrupted = []

        for content_hash in self.list_all():
            if self.verify_integrity(content_hash):
                valid_count += 1
            else:
                corrupted.append(content_hash)

        return valid_count, corrupted

    def get_stats(self) -> dict:
        """
        Get statistics about the object store.
        Returns dict with count, total_size, and shard_distribution.
        """
        total_count = 0
        total_size = 0
        shard_counts: dict[str, int] = {}

        if not self.path.exists():
            return {
                "count": 0,
                "total_size_bytes": 0,
                "shard_distribution": {},
            }

        for shard_dir in self.path.iterdir():
            if shard_dir.is_dir() and len(shard_dir.name) == 2:
                shard_count = 0
                for obj_file in shard_dir.iterdir():
                    if obj_file.is_file() and obj_file.suffix == ".json":
                        total_count += 1
                        shard_count += 1
                        try:
                            total_size += obj_file.stat().st_size
                        except OSError:
                            pass
                if shard_count > 0:
                    shard_counts[shard_dir.name] = shard_count

        return {
            "count": total_count,
            "total_size_bytes": total_size,
            "shard_distribution": shard_counts,
        }
