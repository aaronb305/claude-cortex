"""Entity graph database management."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Generator
import fnmatch

from claude_cortex.entities.models import Entity, Relationship, EntityType, RelationshipType
from claude_cortex.entities.schema import get_full_schema

logger = logging.getLogger(__name__)


class EntityGraph:
    """Manages the entity graph database for code structure tracking."""

    def __init__(
        self,
        db_path: Optional[Path] = None,
        project_dir: Optional[Path] = None,
    ):
        """Initialize the entity graph.

        Args:
            db_path: Path to SQLite database. Defaults based on project_dir.
            project_dir: Project directory for project-local graph.
                        If None, uses global graph at ~/.claude/cache/entities.db
        """
        if db_path is None:
            if project_dir:
                db_path = Path(project_dir) / ".claude" / "cache" / "entities.db"
            else:
                db_path = Path.home() / ".claude" / "cache" / "entities.db"

        self.db_path = Path(db_path)
        self.project_dir = Path(project_dir) if project_dir else None
        self._connection: Optional[sqlite3.Connection] = None
        self._file_hashes: dict[str, str] = {}
        self._ensure_structure()

    def __enter__(self) -> "EntityGraph":
        _ = self.connection
        return self

    def __exit__(self, *args) -> None:
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        """Get or create database connection."""
        if self._connection is None:
            self._connection = sqlite3.connect(str(self.db_path), timeout=30.0)
            self._connection.row_factory = sqlite3.Row
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
        return self._connection

    def _ensure_structure(self) -> None:
        """Create database directory and tables."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._create_tables()
        self._load_file_hashes()

    def _create_tables(self) -> None:
        """Execute schema creation."""
        conn = self.connection
        conn.executescript(get_full_schema())
        conn.commit()

    def _load_file_hashes(self) -> None:
        """Load file content hashes for staleness detection."""
        hash_file = self.db_path.parent / "file_hashes.json"
        if hash_file.exists():
            try:
                with open(hash_file) as f:
                    self._file_hashes = json.load(f)
            except (json.JSONDecodeError, IOError):
                self._file_hashes = {}

    def _save_file_hashes(self) -> None:
        """Save file content hashes."""
        hash_file = self.db_path.parent / "file_hashes.json"
        try:
            with open(hash_file, "w") as f:
                json.dump(self._file_hashes, f, indent=2)
        except IOError:
            pass  # Non-critical

    def is_stale(self, file_path: Path) -> bool:
        """Check if a file needs re-indexing based on content hash.

        Args:
            file_path: Path to the file

        Returns:
            True if file has changed or is not indexed
        """
        file_str = str(file_path)
        stored_hash = self._file_hashes.get(file_str)

        if stored_hash is None:
            return True

        try:
            current_hash = hashlib.md5(file_path.read_bytes()).hexdigest()
            return stored_hash != current_hash
        except IOError:
            return True

    def index_file(self, file_path: Path, force: bool = False) -> int:
        """Extract and store entities from a single file.

        Args:
            file_path: Path to the source file
            force: Re-index even if not stale

        Returns:
            Number of entities indexed
        """
        file_path = Path(file_path)

        if not force and not self.is_stale(file_path):
            return 0

        # Get appropriate extractor
        from claude_cortex.entities.extractors import get_extractor_for_file

        extractor = get_extractor_for_file(str(file_path))
        if extractor is None:
            return 0

        # Extract entities
        result = extractor.extract_file(file_path)

        if result.errors:
            # Log errors but continue
            for error in result.errors:
                logger.warning("Entity extraction error: %s", error)

        if not result.entities:
            return 0

        conn = self.connection
        file_str = str(file_path)

        # Delete existing entities for this file
        conn.execute("DELETE FROM entities WHERE file_path = ?", (file_str,))

        # Insert new entities and track their IDs
        entity_ids: dict[str, int] = {}

        for entity in result.entities:
            cursor = conn.execute(
                """
                INSERT INTO entities (
                    entity_type, name, qualified_name, file_path,
                    start_line, end_line, content_hash, last_indexed, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity.entity_type.value,
                    entity.name,
                    entity.qualified_name,
                    entity.file_path,
                    entity.start_line,
                    entity.end_line,
                    entity.content_hash,
                    entity.last_indexed,
                    json.dumps(entity.metadata) if entity.metadata else None,
                ),
            )
            entity_ids[entity.qualified_name] = cursor.lastrowid

        # Insert relationships (where both source and target exist)
        for source_name, target_name, rel_type, metadata in result.relationships:
            source_id = entity_ids.get(source_name)

            # Target might be in this file or external
            target_id = entity_ids.get(target_name)
            if target_id is None:
                # Try to find existing entity with this name
                cursor = conn.execute(
                    "SELECT id FROM entities WHERE qualified_name = ? OR name = ?",
                    (target_name, target_name),
                )
                row = cursor.fetchone()
                if row:
                    target_id = row[0]

            if source_id and target_id:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO relationships (
                        source_id, target_id, relationship_type, weight, metadata
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        source_id,
                        target_id,
                        rel_type.value,
                        1.0,
                        json.dumps(metadata) if metadata else None,
                    ),
                )

        conn.commit()

        # Update file hash
        try:
            self._file_hashes[file_str] = hashlib.md5(file_path.read_bytes()).hexdigest()
            self._save_file_hashes()
        except IOError:
            pass

        return len(result.entities)

    def index_directory(
        self,
        directory: Path,
        patterns: Optional[list[str]] = None,
        force: bool = False,
    ) -> tuple[int, int]:
        """Index all matching files in directory.

        Args:
            directory: Directory to index
            patterns: Glob patterns to match (default: Python and TypeScript)
            force: Re-index all files even if not stale

        Returns:
            Tuple of (files_indexed, entities_indexed)
        """
        if patterns is None:
            patterns = ["**/*.py", "**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx"]

        directory = Path(directory)
        files_indexed = 0
        entities_indexed = 0

        # Collect all matching files
        files_to_index: set[Path] = set()
        for pattern in patterns:
            for file_path in directory.glob(pattern):
                if file_path.is_file():
                    # Skip common non-source directories
                    parts = file_path.parts
                    if any(
                        p in parts
                        for p in [
                            "node_modules",
                            "__pycache__",
                            ".venv",
                            "venv",
                            ".git",
                            "dist",
                            "build",
                        ]
                    ):
                        continue
                    files_to_index.add(file_path)

        for file_path in files_to_index:
            count = self.index_file(file_path, force=force)
            if count > 0:
                files_indexed += 1
                entities_indexed += count

        return files_indexed, entities_indexed

    def get_entity(self, qualified_name: str) -> Optional[Entity]:
        """Get entity by qualified name (file:entity).

        Args:
            qualified_name: The full qualified name

        Returns:
            Entity or None if not found
        """
        cursor = self.connection.execute(
            "SELECT * FROM entities WHERE qualified_name = ?",
            (qualified_name,),
        )
        row = cursor.fetchone()
        return Entity.from_row(row) if row else None

    def get_entity_by_id(self, entity_id: int) -> Optional[Entity]:
        """Get entity by database ID.

        Args:
            entity_id: The entity's database ID

        Returns:
            Entity or None if not found
        """
        cursor = self.connection.execute(
            "SELECT * FROM entities WHERE id = ?",
            (entity_id,),
        )
        row = cursor.fetchone()
        return Entity.from_row(row) if row else None

    def get_entities_in_file(self, file_path: str) -> list[Entity]:
        """Get all entities defined in a file.

        Args:
            file_path: Path to the file

        Returns:
            List of Entity objects
        """
        cursor = self.connection.execute(
            "SELECT * FROM entities WHERE file_path = ? ORDER BY start_line",
            (file_path,),
        )
        return [Entity.from_row(row) for row in cursor.fetchall()]

    def get_entities_by_type(
        self,
        entity_type: EntityType,
        limit: int = 100,
    ) -> list[Entity]:
        """Get entities by type.

        Args:
            entity_type: The type of entities to retrieve
            limit: Maximum number of results

        Returns:
            List of Entity objects
        """
        cursor = self.connection.execute(
            "SELECT * FROM entities WHERE entity_type = ? LIMIT ?",
            (entity_type.value, limit),
        )
        return [Entity.from_row(row) for row in cursor.fetchall()]

    def get_dependencies(self, entity_id: int, depth: int = 1) -> list[Relationship]:
        """Get what this entity depends on (outgoing relationships).

        Args:
            entity_id: The source entity's database ID
            depth: Depth of traversal (1 = direct only, max 10)

        Returns:
            List of Relationship objects
        """
        # Validate depth to prevent excessive recursion
        depth = max(1, min(depth, 10))

        if depth == 1:
            cursor = self.connection.execute(
                """
                SELECT r.*,
                       e.qualified_name as target_qualified_name,
                       e.name as target_name,
                       e.entity_type as target_type
                FROM relationships r
                JOIN entities e ON r.target_id = e.id
                WHERE r.source_id = ?
                """,
                (entity_id,),
            )
        else:
            # Use recursive CTE for deeper traversal
            cursor = self.connection.execute(
                """
                WITH RECURSIVE deps(id, source_id, target_id, relationship_type, weight, metadata, depth) AS (
                    SELECT id, source_id, target_id, relationship_type, weight, metadata, 1
                    FROM relationships
                    WHERE source_id = ?

                    UNION ALL

                    SELECT r.id, r.source_id, r.target_id, r.relationship_type, r.weight, r.metadata, d.depth + 1
                    FROM relationships r
                    JOIN deps d ON r.source_id = d.target_id
                    WHERE d.depth < ?
                )
                SELECT DISTINCT d.*,
                       e.qualified_name as target_qualified_name,
                       e.name as target_name,
                       e.entity_type as target_type
                FROM deps d
                JOIN entities e ON d.target_id = e.id
                """,
                (entity_id, depth),
            )

        relationships = []
        for row in cursor.fetchall():
            rel = Relationship.from_row(row)
            rel.target_entity = Entity(
                id=row["target_id"],
                entity_type=EntityType(row["target_type"]),
                name=row["target_name"],
                qualified_name=row["target_qualified_name"],
                file_path="",  # Not fetched for efficiency
            )
            relationships.append(rel)

        return relationships

    def get_dependents(self, entity_id: int, depth: int = 1) -> list[Relationship]:
        """Get what depends on this entity (incoming relationships).

        Args:
            entity_id: The target entity's database ID
            depth: Depth of traversal (1 = direct only, max 10)

        Returns:
            List of Relationship objects
        """
        # Validate depth to prevent excessive recursion
        depth = max(1, min(depth, 10))

        if depth == 1:
            cursor = self.connection.execute(
                """
                SELECT r.*,
                       e.qualified_name as source_qualified_name,
                       e.name as source_name,
                       e.entity_type as source_type
                FROM relationships r
                JOIN entities e ON r.source_id = e.id
                WHERE r.target_id = ?
                """,
                (entity_id,),
            )
        else:
            cursor = self.connection.execute(
                """
                WITH RECURSIVE deps(id, source_id, target_id, relationship_type, weight, metadata, depth) AS (
                    SELECT id, source_id, target_id, relationship_type, weight, metadata, 1
                    FROM relationships
                    WHERE target_id = ?

                    UNION ALL

                    SELECT r.id, r.source_id, r.target_id, r.relationship_type, r.weight, r.metadata, d.depth + 1
                    FROM relationships r
                    JOIN deps d ON r.target_id = d.source_id
                    WHERE d.depth < ?
                )
                SELECT DISTINCT d.*,
                       e.qualified_name as source_qualified_name,
                       e.name as source_name,
                       e.entity_type as source_type
                FROM deps d
                JOIN entities e ON d.source_id = e.id
                """,
                (entity_id, depth),
            )

        relationships = []
        for row in cursor.fetchall():
            rel = Relationship.from_row(row)
            rel.source_entity = Entity(
                id=row["source_id"],
                entity_type=EntityType(row["source_type"]),
                name=row["source_name"],
                qualified_name=row["source_qualified_name"],
                file_path="",
            )
            relationships.append(rel)

        return relationships

    def search(self, query: str, limit: int = 20) -> list[Entity]:
        """Full-text search for entities by name.

        Args:
            query: Search query (FTS5 special chars are escaped for literal matching)
            limit: Maximum results

        Returns:
            List of matching Entity objects
        """
        # Escape FTS5 special characters for literal matching
        # FTS5 special: " * ( ) - : ^ OR AND NOT NEAR
        escaped_query = query.replace('"', '""')
        # Wrap in quotes for literal phrase matching
        safe_query = f'"{escaped_query}"'

        try:
            cursor = self.connection.execute(
                """
                SELECT e.* FROM entities e
                JOIN entities_fts fts ON e.id = fts.rowid
                WHERE entities_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (safe_query, limit),
            )
            return [Entity.from_row(row) for row in cursor.fetchall()]
        except Exception:
            # Fall back to LIKE query if FTS5 fails
            cursor = self.connection.execute(
                """
                SELECT * FROM entities
                WHERE name LIKE ? OR qualified_name LIKE ?
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", limit),
            )
            return [Entity.from_row(row) for row in cursor.fetchall()]

    def get_stats(self) -> dict:
        """Get statistics about the entity graph.

        Returns:
            Dictionary with entity and relationship counts
        """
        cursor = self.connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM entities) as entity_count,
                (SELECT COUNT(*) FROM entities WHERE entity_type = 'file') as file_count,
                (SELECT COUNT(*) FROM entities WHERE entity_type = 'function') as function_count,
                (SELECT COUNT(*) FROM entities WHERE entity_type = 'class') as class_count,
                (SELECT COUNT(*) FROM entities WHERE entity_type = 'method') as method_count,
                (SELECT COUNT(*) FROM relationships) as relationship_count
            """
        )
        row = cursor.fetchone()
        return {
            "entities": row["entity_count"],
            "files": row["file_count"],
            "functions": row["function_count"],
            "classes": row["class_count"],
            "methods": row["method_count"],
            "relationships": row["relationship_count"],
        }

    def clear(self) -> None:
        """Clear all entities and relationships."""
        conn = self.connection
        conn.execute("DELETE FROM relationships")
        conn.execute("DELETE FROM entities")
        conn.commit()
        self._file_hashes = {}
        self._save_file_hashes()

    def close(self) -> None:
        """Close database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
