"""Full-text search module for learnings.

Provides both keyword-based (FTS5) and semantic (vector) search:
    - SearchIndex: SQLite FTS5 full-text search (always available)
    - SemanticIndex: Vector similarity search (requires optional deps)

For semantic search, install optional dependencies:
    uv add sentence-transformers sqlite-vec
"""

from .index import SearchIndex, SearchResult
from .semantic import SemanticIndex, SemanticSearchResult, is_available as semantic_available

__all__ = [
    "SearchIndex",
    "SearchResult",
    "SemanticIndex",
    "SemanticSearchResult",
    "semantic_available",
]
