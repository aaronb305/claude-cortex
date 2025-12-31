"""Semantic search using FastEmbed and sqlite-vec.

This module provides semantic/vector search capabilities for learnings,
complementing the FTS5-based keyword search. It uses FastEmbed (ONNX-based)
for embedding generation and sqlite-vec for efficient vector storage/search.

FastEmbed is much lighter than sentence-transformers:
- FastEmbed: ~187 MB (ONNX Runtime)
- sentence-transformers: ~6.9 GB (PyTorch + CUDA)

Dependencies:
    uv add fastembed sqlite-vec
"""

import hashlib
import sqlite3
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..ledger import Ledger

# Track availability of dependencies
_FASTEMBED_AVAILABLE = False
_SQLITE_VEC_AVAILABLE = False

try:
    from fastembed import TextEmbedding
    _FASTEMBED_AVAILABLE = True
except ImportError:
    TextEmbedding = None  # type: ignore

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
    return _FASTEMBED_AVAILABLE and _SQLITE_VEC_AVAILABLE


class SemanticIndex:
    """Semantic search index using FastEmbed and sqlite-vec.

    Uses the BAAI/bge-small-en-v1.5 model which provides excellent quality
    with a small footprint. FastEmbed uses ONNX Runtime for efficient
    CPU-based inference without requiring PyTorch.

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

    Install dependencies:
        uv add fastembed sqlite-vec
    """

    # Model configuration - bge-small-en-v1.5 is high quality and fast
    MODEL_NAME = "BAAI/bge-small-en-v1.5"
    EMBEDDING_DIM = 384  # Dimension for bge-small-en-v1.5

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
            if not _FASTEMBED_AVAILABLE:
                missing.append("fastembed")
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
        self._model: Optional["TextEmbedding"] = None
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
            self._connection = sqlite3.connect(str(self.db_path), timeout=30.0)
            self._connection.row_factory = sqlite3.Row
            # Load the sqlite-vec extension
            self._connection.enable_load_extension(True)
            sqlite_vec.load(self._connection)
            self._connection.enable_load_extension(False)
        return self._connection

    @property
    def model(self) -> "TextEmbedding":
        """Get or load the embedding model (lazy loading)."""
        if self._model is None:
            self._model = TextEmbedding(self.MODEL_NAME)
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
        return hashlib.md5(content.encode()).hexdigest()

    def _embed_single(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        # FastEmbed returns a generator, get first (only) result
        embeddings = list(self.model.embed([text]))
        return embeddings[0].tolist()

    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts efficiently."""
        embeddings = list(self.model.embed(texts))
        return [emb.tolist() for emb in embeddings]

    def index_learning(self, learning_id: str, content: str) -> bool:
        """Add or update a learning in the semantic index.

        Generates an embedding for the content and stores it for
        similarity search.

        Args:
            learning_id: Unique identifier for the learning
            content: The text content to embed and index

        Returns:
            True if indexing succeeded, False on error
        """
        try:
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
                    return True

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
            embedding = self._embed_single(content)

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
            return True
        except sqlite3.Error as e:
            print(f"[SemanticIndex] Error indexing learning {learning_id}: {e}", file=sys.stderr)
            try:
                self.connection.rollback()
            except sqlite3.Error:
                pass
            return False
        except Exception as e:
            print(f"[SemanticIndex] Embedding error for {learning_id}: {e}", file=sys.stderr)
            try:
                self.connection.rollback()
            except sqlite3.Error:
                pass
            return False

    def index_learnings_batch(
        self,
        learnings: list[tuple[str, str]],
        batch_size: int = 32,
    ) -> tuple[int, int]:
        """Index multiple learnings efficiently with batch embedding.

        Args:
            learnings: List of (learning_id, content) tuples
            batch_size: Number of embeddings to generate at once

        Returns:
            Tuple of (successfully_indexed, failed_count)
        """
        if not learnings:
            return (0, 0)

        indexed = 0
        failed = 0

        # Process in batches
        for i in range(0, len(learnings), batch_size):
            batch = learnings[i:i + batch_size]

            try:
                cursor = self.connection.cursor()

                # Check which need indexing (content changed)
                to_index = []
                for learning_id, content in batch:
                    content_hash = self._hash_content(content)
                    cursor.execute(
                        "SELECT id, content_hash FROM learning_embeddings WHERE learning_id = ?",
                        (learning_id,)
                    )
                    existing = cursor.fetchone()

                    if existing:
                        if existing["content_hash"] == content_hash:
                            continue  # Skip unchanged
                        # Remove old entry
                        cursor.execute("DELETE FROM vec_embeddings WHERE id = ?", (existing["id"],))
                        cursor.execute("DELETE FROM learning_embeddings WHERE id = ?", (existing["id"],))

                    to_index.append((learning_id, content, content_hash))

                if not to_index:
                    continue

                # Batch embed
                contents = [content for _, content, _ in to_index]
                try:
                    embeddings = self._embed_batch(contents)
                except Exception as e:
                    print(f"[SemanticIndex] Batch embedding error: {e}", file=sys.stderr)
                    failed += len(to_index)
                    try:
                        self.connection.rollback()
                    except sqlite3.Error:
                        pass
                    continue

                # Insert all
                for (learning_id, _, content_hash), embedding in zip(to_index, embeddings):
                    try:
                        cursor.execute(
                            "INSERT INTO learning_embeddings (learning_id, content_hash) VALUES (?, ?)",
                            (learning_id, content_hash)
                        )
                        row_id = cursor.lastrowid

                        embedding_bytes = self._serialize_embedding(embedding)
                        cursor.execute(
                            "INSERT INTO vec_embeddings (id, embedding) VALUES (?, ?)",
                            (row_id, embedding_bytes)
                        )
                        indexed += 1
                    except sqlite3.Error as e:
                        print(f"[SemanticIndex] Error inserting {learning_id}: {e}", file=sys.stderr)
                        failed += 1

                # Commit each batch
                self.connection.commit()
            except sqlite3.Error as e:
                print(f"[SemanticIndex] Batch error: {e}", file=sys.stderr)
                failed += len(batch)
                try:
                    self.connection.rollback()
                except sqlite3.Error:
                    pass

        return (indexed, failed)

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
        query_embedding = self._embed_single(query)
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

    def reindex_ledger(self, ledger: "Ledger") -> tuple[int, int]:
        """Rebuild the entire semantic index from a ledger.

        Uses batch embedding for efficiency.

        Args:
            ledger: The Ledger instance to index from

        Returns:
            Tuple of (successfully_indexed, failed_count)
        """
        try:
            cursor = self.connection.cursor()

            # Clear existing index
            cursor.execute("DELETE FROM vec_embeddings")
            cursor.execute("DELETE FROM learning_embeddings")
            self.connection.commit()
        except sqlite3.Error as e:
            print(f"[SemanticIndex] Error clearing index: {e}", file=sys.stderr)
            try:
                self.connection.rollback()
            except sqlite3.Error:
                pass
            return (0, 0)

        # Collect all learnings
        learnings = []
        for block in ledger.get_all_blocks():
            for learning in block.learnings:
                learnings.append((learning.id, learning.content))

        # Use batch indexing for efficiency
        return self.index_learnings_batch(learnings)

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
