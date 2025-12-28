"""Semantic search using sentence-transformers and sqlite-vec.

This module provides semantic/vector search capabilities for learnings,
complementing the FTS5-based keyword search. It uses sentence-transformers
for embedding generation and sqlite-vec for efficient vector storage/search.

Dependencies are optional - the module gracefully falls back if unavailable:
    uv add sentence-transformers sqlite-vec
"""

import sqlite3
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Track availability of optional dependencies
_SENTENCE_TRANSFORMERS_AVAILABLE = False
_SQLITE_VEC_AVAILABLE = False

try:
    from sentence_transformers import SentenceTransformer
    _SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SentenceTransformer = None  # type: ignore

try:
    import sqlite_vec
    _SQLITE_VEC_AVAILABLE = True
except ImportError:
    sqlite_vec = None  # type: ignore


@dataclass
class SemanticSearchResult:
    """A single semantic search result."""

    learning_id: str
    score: float  # Cosine similarity score (higher is better)


def is_available() -> bool:
    """Check if semantic search dependencies are available."""
    return _SENTENCE_TRANSFORMERS_AVAILABLE and _SQLITE_VEC_AVAILABLE


class SemanticIndex:
    """Semantic search index using sentence-transformers and sqlite-vec.

    Uses the all-MiniLM-L6-v2 model which provides a good balance of
    speed and quality for general-purpose semantic search.

    Embeddings are stored in SQLite using the sqlite-vec extension,
    enabling efficient cosine similarity search.

    Example:
        # Check if available first
        if SemanticIndex.is_available():
            with SemanticIndex() as index:
                index.index_learning("id1", "This is a learning about Python")
                results = index.search("programming language")
                for learning_id, score in results:
                    print(f"{learning_id}: {score}")

    Falls back gracefully if dependencies are not installed:
        uv add sentence-transformers sqlite-vec
    """

    # Model configuration
    MODEL_NAME = "all-MiniLM-L6-v2"
    EMBEDDING_DIM = 384  # Dimension for all-MiniLM-L6-v2

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize the semantic index.

        Args:
            db_path: Path to SQLite database file.
                     Defaults to ~/.claude/cache/semantic.db

        Raises:
            ImportError: If required dependencies are not available
        """
        if not is_available():
            missing = []
            if not _SENTENCE_TRANSFORMERS_AVAILABLE:
                missing.append("sentence-transformers")
            if not _SQLITE_VEC_AVAILABLE:
                missing.append("sqlite-vec")
            raise ImportError(
                f"Semantic search requires: {', '.join(missing)}. "
                f"Install with: uv add {' '.join(missing)}"
            )

        if db_path is None:
            cache_dir = Path.home() / ".claude" / "cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            db_path = cache_dir / "semantic.db"

        self.db_path = db_path
        self._connection: Optional[sqlite3.Connection] = None
        self._model: Optional["SentenceTransformer"] = None
        self._in_context: bool = False
        self._create_tables()

    @staticmethod
    def is_available() -> bool:
        """Check if semantic search dependencies are available."""
        return is_available()

    def __enter__(self) -> "SemanticIndex":
        """Enter context manager, keeping connection open."""
        self._in_context = True
        _ = self.connection  # Ensure connection is established
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager, closing connection."""
        self._in_context = False
        self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        """Get or create the database connection with sqlite-vec loaded."""
        if self._connection is None:
            self._connection = sqlite3.connect(str(self.db_path))
            self._connection.row_factory = sqlite3.Row
            # Load the sqlite-vec extension
            self._connection.enable_load_extension(True)
            sqlite_vec.load(self._connection)
            self._connection.enable_load_extension(False)
        return self._connection

    @property
    def model(self) -> "SentenceTransformer":
        """Get or load the sentence transformer model (lazy loading)."""
        if self._model is None:
            self._model = SentenceTransformer(self.MODEL_NAME)
        return self._model

    def close(self) -> None:
        """Close the database connection."""
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def _create_tables(self) -> None:
        """Create the vector table for embeddings if it doesn't exist."""
        cursor = self.connection.cursor()

        # Create a regular table to map learning IDs to rowids
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS learning_embeddings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                learning_id TEXT UNIQUE NOT NULL,
                content_hash TEXT
            )
        """)

        # Create the virtual table for vector search
        # Uses cosine distance for semantic similarity
        cursor.execute(f"""
            CREATE VIRTUAL TABLE IF NOT EXISTS vec_embeddings USING vec0(
                id INTEGER PRIMARY KEY,
                embedding FLOAT[{self.EMBEDDING_DIM}]
            )
        """)

        # Create index on learning_id for fast lookups
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_learning_id
            ON learning_embeddings(learning_id)
        """)

        self.connection.commit()

    def _serialize_embedding(self, embedding: list[float]) -> bytes:
        """Serialize embedding to bytes for sqlite-vec."""
        return struct.pack(f"{len(embedding)}f", *embedding)

    def _hash_content(self, content: str) -> str:
        """Create a simple hash of content for change detection."""
        import hashlib
        return hashlib.md5(content.encode()).hexdigest()

    def index_learning(self, learning_id: str, content: str) -> None:
        """Add or update a learning in the semantic index.

        Generates an embedding for the content and stores it for
        similarity search.

        Args:
            learning_id: Unique identifier for the learning
            content: The text content to embed and index
        """
        cursor = self.connection.cursor()
        content_hash = self._hash_content(content)

        # Check if learning already exists and if content changed
        cursor.execute(
            "SELECT id, content_hash FROM learning_embeddings WHERE learning_id = ?",
            (learning_id,)
        )
        existing = cursor.fetchone()

        if existing:
            if existing["content_hash"] == content_hash:
                # Content unchanged, skip re-indexing
                return

            # Content changed, remove old embedding
            cursor.execute(
                "DELETE FROM vec_embeddings WHERE id = ?",
                (existing["id"],)
            )
            cursor.execute(
                "DELETE FROM learning_embeddings WHERE id = ?",
                (existing["id"],)
            )

        # Generate embedding
        embedding = self.model.encode(content, convert_to_numpy=True).tolist()

        # Insert into mapping table
        cursor.execute(
            "INSERT INTO learning_embeddings (learning_id, content_hash) VALUES (?, ?)",
            (learning_id, content_hash)
        )
        row_id = cursor.lastrowid

        # Insert embedding into vector table
        embedding_bytes = self._serialize_embedding(embedding)
        cursor.execute(
            "INSERT INTO vec_embeddings (id, embedding) VALUES (?, ?)",
            (row_id, embedding_bytes)
        )

        self.connection.commit()

    def search(self, query: str, limit: int = 10) -> list[tuple[str, float]]:
        """Search for semantically similar learnings.

        Args:
            query: The search query text
            limit: Maximum number of results to return

        Returns:
            List of (learning_id, score) tuples, sorted by similarity (highest first).
            Score is cosine similarity (0 to 1, higher is more similar).
        """
        if not query.strip():
            return []

        cursor = self.connection.cursor()

        # Generate query embedding
        query_embedding = self.model.encode(query, convert_to_numpy=True).tolist()
        query_bytes = self._serialize_embedding(query_embedding)

        # Search using sqlite-vec's KNN search
        # vec_distance_cosine returns distance (0 = identical), so we convert to similarity
        cursor.execute(
            """
            SELECT
                le.learning_id,
                1 - vec_distance_cosine(ve.embedding, ?) as similarity
            FROM vec_embeddings ve
            JOIN learning_embeddings le ON le.id = ve.id
            ORDER BY vec_distance_cosine(ve.embedding, ?)
            LIMIT ?
            """,
            (query_bytes, query_bytes, limit)
        )

        results = []
        for row in cursor.fetchall():
            results.append((row["learning_id"], float(row["similarity"])))

        return results

    def delete_learning(self, learning_id: str) -> bool:
        """Remove a learning from the semantic index.

        Args:
            learning_id: The ID of the learning to remove

        Returns:
            True if the learning was found and deleted, False otherwise
        """
        cursor = self.connection.cursor()

        cursor.execute(
            "SELECT id FROM learning_embeddings WHERE learning_id = ?",
            (learning_id,)
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                "DELETE FROM vec_embeddings WHERE id = ?",
                (existing["id"],)
            )
            cursor.execute(
                "DELETE FROM learning_embeddings WHERE id = ?",
                (existing["id"],)
            )
            self.connection.commit()
            return True

        return False

    def reindex_ledger(self, ledger: "Ledger") -> int:
        """Rebuild the entire semantic index from a ledger.

        Clears all existing entries and reindexes all learnings.

        Args:
            ledger: The Ledger instance to index from

        Returns:
            Number of learnings indexed
        """
        cursor = self.connection.cursor()

        # Clear existing index
        cursor.execute("DELETE FROM vec_embeddings")
        cursor.execute("DELETE FROM learning_embeddings")
        self.connection.commit()

        count = 0
        for block in ledger.get_all_blocks():
            for learning in block.learnings:
                self.index_learning(learning.id, learning.content)
                count += 1

        return count

    def get_stats(self) -> dict:
        """Get statistics about the semantic index.

        Returns:
            Dictionary with index statistics
        """
        cursor = self.connection.cursor()

        cursor.execute("SELECT COUNT(*) as total FROM learning_embeddings")
        total = cursor.fetchone()["total"]

        return {
            "total_indexed": total,
            "model": self.MODEL_NAME,
            "embedding_dim": self.EMBEDDING_DIM,
            "database_path": str(self.db_path),
            "available": True,
        }
