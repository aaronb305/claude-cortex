"""SQLite FTS5 search index for learnings."""

import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..ledger.models import LearningCategory


@dataclass
class SearchResult:
    """A single search result with snippet."""

    learning_id: str
    category: str
    content: str
    confidence: float
    source: Optional[str]
    snippet: str
    rank: float


class SearchIndex:
    """SQLite FTS5 full-text search index for learnings.

    Uses porter stemming and unicode61 tokenizer for robust search
    across learning content.

    Supports context manager pattern for proper connection management:
        with SearchIndex(db_path) as index:
            index.search("query")
            index.index_learning(...)
    """

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize the search index.

        Args:
            db_path: Path to SQLite database file.
                     Defaults to ~/.claude/cache/search.db
        """
        if db_path is None:
            cache_dir = Path.home() / ".claude" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_path = cache_dir / "search.db"

        self.db_path = db_path
        self._connection: Optional[sqlite3.Connection] = None
        self._in_context: bool = False
        self.create_tables()

    def __enter__(self) -> "SearchIndex":
        """Enter context manager, keeping connection open."""
        self._in_context = True
        # Ensure connection is established
        _ = self.connection
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager, closing connection."""
        self._in_context = False
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        """Get or create the database connection."""
        if self._connection is None:
            self._connection = sqlite3.connect(str(self.db_path), timeout=30.0)
            self._connection.row_factory = sqlite3.Row
        return self._connection

    def close(self) -> None:
        """Close the database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def create_tables(self) -> None:
        """Create the FTS5 virtual table for learnings if it doesn't exist."""
        cursor = self.connection.cursor()

        # Create FTS5 virtual table with porter stemmer and unicode61 tokenizer
        cursor.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS learnings_fts USING fts5(
                learning_id UNINDEXED,
                category,
                content,
                confidence UNINDEXED,
                source,
                tokenize='porter unicode61'
            )
        """)

        self.connection.commit()

    def index_learning(
        self,
        learning_id: str,
        category: str,
        content: str,
        confidence: float,
        source: Optional[str] = None,
        commit: bool = True,
    ) -> bool:
        """Add a learning to the search index.

        If the learning already exists, it will be updated.

        Args:
            learning_id: Unique identifier for the learning
            category: Learning category (discovery, decision, error, pattern)
            content: The full text content of the learning
            confidence: Confidence score (0.0 to 1.0)
            source: Optional source file or context
            commit: Whether to commit after this insert (False for batch operations)

        Returns:
            True if indexing succeeded, False on error
        """
        try:
            cursor = self.connection.cursor()

            # Check if learning already exists
            cursor.execute(
                "SELECT rowid FROM learnings_fts WHERE learning_id = ?",
                (learning_id,)
            )
            existing = cursor.fetchone()

            if existing:
                # Delete existing entry before inserting updated one
                cursor.execute(
                    "DELETE FROM learnings_fts WHERE learning_id = ?",
                    (learning_id,)
                )

            # Insert the learning
            cursor.execute(
                """
                INSERT INTO learnings_fts (learning_id, category, content, confidence, source)
                VALUES (?, ?, ?, ?, ?)
                """,
                (learning_id, category, content, confidence, source or ""),
            )

            if commit:
                self.connection.commit()
            return True
        except sqlite3.Error as e:
            print(f"[SearchIndex] Error indexing learning {learning_id}: {e}", file=sys.stderr)
            try:
                self.connection.rollback()
            except sqlite3.Error:
                pass
            return False

    def reindex_ledger(self, ledger: "Ledger") -> int:
        """Rebuild the entire search index from a ledger.

        Clears all existing entries and reindexes all learnings from the ledger.
        Uses batch commits for better performance.

        Args:
            ledger: The Ledger instance to index from

        Returns:
            Number of learnings indexed
        """
        cursor = self.connection.cursor()

        # Clear existing index
        cursor.execute("DELETE FROM learnings_fts")

        count = 0
        for block in ledger.get_all_blocks():
            for learning in block.learnings:
                # Use commit=False for batch operation
                self.index_learning(
                    learning_id=learning.id,
                    category=learning.category.value,
                    content=learning.content,
                    confidence=learning.confidence,
                    source=learning.source,
                    commit=False,
                )
                count += 1

        # Single commit at the end for all inserts
        self.connection.commit()
        return count

    def search(
        self,
        query: str,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Perform a full-text search across all learnings.

        Uses FTS5's built-in ranking (BM25) to order results by relevance.

        Args:
            query: The search query (supports FTS5 query syntax)
            limit: Maximum number of results to return

        Returns:
            List of SearchResult objects sorted by relevance
        """
        if not query.strip():
            return []

        try:
            cursor = self.connection.cursor()

            # Use FTS5 match query with BM25 ranking and snippet generation
            cursor.execute(
                """
                SELECT
                    learning_id,
                    category,
                    content,
                    confidence,
                    source,
                    snippet(learnings_fts, 2, '<mark>', '</mark>', '...', 64) as snippet,
                    rank
                FROM learnings_fts
                WHERE learnings_fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, limit),
            )

            results = []
            for row in cursor.fetchall():
                results.append(
                    SearchResult(
                        learning_id=row["learning_id"],
                        category=row["category"],
                        content=row["content"],
                        confidence=float(row["confidence"]),
                        source=row["source"] if row["source"] else None,
                        snippet=row["snippet"],
                        rank=float(row["rank"]),
                    )
                )

            return results
        except sqlite3.OperationalError as e:
            # Handle malformed FTS5 queries (e.g., unbalanced quotes, invalid syntax)
            print(f"[SearchIndex] FTS5 query error for '{query}': {e}", file=sys.stderr)
            return []
        except sqlite3.Error as e:
            print(f"[SearchIndex] Search error: {e}", file=sys.stderr)
            return []

    def search_by_category(
        self,
        query: str,
        category: str,
        limit: int = 20,
    ) -> list[SearchResult]:
        """Perform a full-text search filtered by category.

        Args:
            query: The search query (supports FTS5 query syntax)
            category: Category to filter by (discovery, decision, error, pattern)
            limit: Maximum number of results to return

        Returns:
            List of SearchResult objects sorted by relevance
        """
        if not query.strip():
            return []

        # Validate category
        try:
            LearningCategory(category)
        except ValueError:
            valid_categories = [c.value for c in LearningCategory]
            raise ValueError(
                f"Invalid category '{category}'. Must be one of: {valid_categories}"
            )

        try:
            cursor = self.connection.cursor()

            # Use separate WHERE clause for category filter since FTS5 column filter
            # syntax requires exact match on the column value
            cursor.execute(
                """
                SELECT
                    learning_id,
                    category,
                    content,
                    confidence,
                    source,
                    snippet(learnings_fts, 2, '<mark>', '</mark>', '...', 64) as snippet,
                    rank
                FROM learnings_fts
                WHERE learnings_fts MATCH ?
                  AND category = ?
                ORDER BY rank
                LIMIT ?
                """,
                (query, category, limit),
            )

            results = []
            for row in cursor.fetchall():
                results.append(
                    SearchResult(
                        learning_id=row["learning_id"],
                        category=row["category"],
                        content=row["content"],
                        confidence=float(row["confidence"]),
                        source=row["source"] if row["source"] else None,
                        snippet=row["snippet"],
                        rank=float(row["rank"]),
                    )
                )

            return results
        except sqlite3.OperationalError as e:
            # Handle malformed FTS5 queries (e.g., unbalanced quotes, invalid syntax)
            print(f"[SearchIndex] FTS5 query error for '{query}': {e}", file=sys.stderr)
            return []
        except sqlite3.Error as e:
            print(f"[SearchIndex] Search error: {e}", file=sys.stderr)
            return []

    def delete_learning(self, learning_id: str) -> bool:
        """Remove a learning from the search index.

        Args:
            learning_id: The ID of the learning to remove

        Returns:
            True if the learning was found and deleted, False otherwise
        """
        cursor = self.connection.cursor()

        cursor.execute(
            "SELECT rowid FROM learnings_fts WHERE learning_id = ?",
            (learning_id,)
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                "DELETE FROM learnings_fts WHERE learning_id = ?",
                (learning_id,)
            )
            self.connection.commit()
            return True

        return False

    def get_stats(self) -> dict:
        """Get statistics about the search index.

        Returns:
            Dictionary with index statistics
        """
        cursor = self.connection.cursor()

        cursor.execute("SELECT COUNT(*) as total FROM learnings_fts")
        total = cursor.fetchone()["total"]

        cursor.execute(
            """
            SELECT category, COUNT(*) as count
            FROM learnings_fts
            GROUP BY category
            """
        )
        by_category = {row["category"]: row["count"] for row in cursor.fetchall()}

        return {
            "total_indexed": total,
            "by_category": by_category,
            "database_path": str(self.db_path),
        }
