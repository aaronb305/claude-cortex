"""Tests for semantic search module."""

import pytest

from continuous_claude.search import SemanticIndex, semantic_available


class TestSemanticAvailability:
    """Test semantic search availability detection."""

    def test_is_available_returns_bool(self):
        """is_available should return a boolean."""
        result = semantic_available()
        assert isinstance(result, bool)

    def test_class_method_matches_module_function(self):
        """SemanticIndex.is_available should match module function."""
        assert SemanticIndex.is_available() == semantic_available()


class TestSemanticIndexWithoutDeps:
    """Tests for SemanticIndex when dependencies are not available."""

    @pytest.mark.skipif(
        semantic_available(),
        reason="Dependencies are installed, skip unavailable tests"
    )
    def test_raises_import_error_without_deps(self, temp_dir):
        """Should raise ImportError with helpful message when deps missing."""
        with pytest.raises(ImportError) as exc_info:
            SemanticIndex(db_path=temp_dir / "semantic.db")

        error_msg = str(exc_info.value)
        assert "uv add" in error_msg
        # Should mention at least one missing dependency
        assert "fastembed" in error_msg or "sqlite-vec" in error_msg


class TestSemanticIndexWithDeps:
    """Tests for SemanticIndex when dependencies are available."""

    @pytest.mark.skipif(
        not semantic_available(),
        reason="Dependencies not installed"
    )
    def test_can_create_index(self, temp_dir):
        """Should be able to create an index when deps available."""
        db_path = temp_dir / "semantic.db"
        with SemanticIndex(db_path=db_path) as index:
            assert index is not None
            assert db_path.exists()

    @pytest.mark.skipif(
        not semantic_available(),
        reason="Dependencies not installed"
    )
    def test_index_and_search(self, temp_dir):
        """Should be able to index content and search."""
        db_path = temp_dir / "semantic.db"
        with SemanticIndex(db_path=db_path) as index:
            # Index some learnings
            index.index_learning("id1", "Python is a programming language")
            index.index_learning("id2", "Machine learning uses neural networks")
            index.index_learning("id3", "Cooking recipes for pasta dishes")

            # Search for programming-related content
            results = index.search("coding and software development", limit=2)

            assert len(results) > 0
            assert isinstance(results[0], tuple)
            assert len(results[0]) == 2
            learning_id, score = results[0]
            assert isinstance(learning_id, str)
            assert isinstance(score, float)
            assert 0 <= score <= 1

    @pytest.mark.skipif(
        not semantic_available(),
        reason="Dependencies not installed"
    )
    def test_delete_learning(self, temp_dir):
        """Should be able to delete a learning."""
        db_path = temp_dir / "semantic.db"
        with SemanticIndex(db_path=db_path) as index:
            index.index_learning("id1", "Test content")

            # Verify it exists
            stats = index.get_stats()
            assert stats["total_indexed"] == 1

            # Delete and verify
            result = index.delete_learning("id1")
            assert result is True

            stats = index.get_stats()
            assert stats["total_indexed"] == 0

            # Delete non-existent
            result = index.delete_learning("id1")
            assert result is False

    @pytest.mark.skipif(
        not semantic_available(),
        reason="Dependencies not installed"
    )
    def test_get_stats(self, temp_dir):
        """Should return valid statistics."""
        db_path = temp_dir / "semantic.db"
        with SemanticIndex(db_path=db_path) as index:
            stats = index.get_stats()

            assert "total_indexed" in stats
            assert "model" in stats
            assert "embedding_dim" in stats
            assert "database_path" in stats
            assert stats["model"] == "BAAI/bge-small-en-v1.5"
            assert stats["embedding_dim"] == 384

    @pytest.mark.skipif(
        not semantic_available(),
        reason="Dependencies not installed"
    )
    def test_update_existing_learning(self, temp_dir):
        """Should update embedding when content changes."""
        db_path = temp_dir / "semantic.db"
        with SemanticIndex(db_path=db_path) as index:
            # Index initial content
            index.index_learning("id1", "Original content about dogs")

            # Update with new content
            index.index_learning("id1", "Updated content about cats")

            # Should still have only one entry
            stats = index.get_stats()
            assert stats["total_indexed"] == 1

            # Should find based on new content
            results = index.search("cats and felines", limit=1)
            assert len(results) == 1
            assert results[0][0] == "id1"

    @pytest.mark.skipif(
        not semantic_available(),
        reason="Dependencies not installed"
    )
    def test_skip_unchanged_content(self, temp_dir):
        """Should skip re-indexing if content hash unchanged."""
        db_path = temp_dir / "semantic.db"
        with SemanticIndex(db_path=db_path) as index:
            content = "Test content that stays the same"

            # Index twice with same content
            index.index_learning("id1", content)
            index.index_learning("id1", content)  # Should be skipped

            # Should still have only one entry
            stats = index.get_stats()
            assert stats["total_indexed"] == 1

    @pytest.mark.skipif(
        not semantic_available(),
        reason="Dependencies not installed"
    )
    def test_empty_query_returns_empty(self, temp_dir):
        """Empty query should return empty results."""
        db_path = temp_dir / "semantic.db"
        with SemanticIndex(db_path=db_path) as index:
            index.index_learning("id1", "Some content")

            results = index.search("")
            assert results == []

            results = index.search("   ")
            assert results == []
