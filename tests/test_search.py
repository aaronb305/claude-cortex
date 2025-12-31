"""Tests for the SearchIndex class."""

import pytest
from pathlib import Path

from claude_cortex.search import SearchIndex


class TestSearchIndexIndexLearning:
    """Tests for SearchIndex.index_learning method."""

    def test_index_learning_adds_to_index(self, search_db_path):
        """Should add a learning to the search index."""
        index = SearchIndex(search_db_path)

        index.index_learning(
            learning_id="test-learning-1",
            category="discovery",
            content="Python uses dynamic typing for flexibility",
            confidence=0.7,
            source="test.py",
        )

        # Verify by searching
        results = index.search("Python dynamic typing")

        assert len(results) >= 1
        assert results[0].learning_id == "test-learning-1"

        index.close()

    def test_index_learning_updates_existing(self, search_db_path):
        """Should update an existing learning when re-indexed."""
        index = SearchIndex(search_db_path)

        # Index initial version
        index.index_learning(
            learning_id="test-learning-2",
            category="pattern",
            content="Original content about testing patterns",
            confidence=0.5,
        )

        # Update with new content
        index.index_learning(
            learning_id="test-learning-2",
            category="pattern",
            content="Updated content about testing best practices",
            confidence=0.8,
        )

        # Search for updated content
        results = index.search("testing best practices")

        assert len(results) >= 1
        assert results[0].learning_id == "test-learning-2"
        assert results[0].confidence == 0.8

        # Verify old content is gone
        old_results = index.search("Original content testing patterns")
        matching = [r for r in old_results if r.learning_id == "test-learning-2"]
        if matching:
            assert "Updated" in matching[0].content

        index.close()


class TestSearchIndexSearch:
    """Tests for SearchIndex.search method."""

    def test_search_returns_results(self, search_db_path):
        """Should return matching results for a query."""
        index = SearchIndex(search_db_path)

        # Add multiple learnings
        index.index_learning(
            learning_id="learning-1",
            category="discovery",
            content="FastAPI is a modern Python web framework",
            confidence=0.8,
        )
        index.index_learning(
            learning_id="learning-2",
            category="pattern",
            content="Use pytest fixtures for test setup",
            confidence=0.7,
        )
        index.index_learning(
            learning_id="learning-3",
            category="error",
            content="Python imports can cause circular dependencies",
            confidence=0.6,
        )

        results = index.search("Python")

        assert len(results) >= 2  # At least learning-1 and learning-3

        index.close()

    def test_search_returns_empty_for_no_match(self, search_db_path):
        """Should return empty list when no matches found."""
        index = SearchIndex(search_db_path)

        index.index_learning(
            learning_id="learning-1",
            category="discovery",
            content="Something about JavaScript and Node.js",
            confidence=0.7,
        )

        results = index.search("Rust programming language")

        assert len(results) == 0

        index.close()

    def test_search_empty_query_returns_empty(self, search_db_path):
        """Should return empty list for empty query."""
        index = SearchIndex(search_db_path)

        index.index_learning(
            learning_id="learning-1",
            category="discovery",
            content="Some learning content here",
            confidence=0.7,
        )

        results = index.search("")
        assert len(results) == 0

        results = index.search("   ")
        assert len(results) == 0

        index.close()

    def test_search_respects_limit(self, search_db_path):
        """Should respect the limit parameter."""
        index = SearchIndex(search_db_path)

        # Add many learnings with same keyword
        for i in range(10):
            index.index_learning(
                learning_id=f"learning-{i}",
                category="pattern",
                content=f"Pattern number {i} about Python programming",
                confidence=0.5,
            )

        results = index.search("Python", limit=3)

        assert len(results) == 3

        index.close()


class TestSearchIndexContextManager:
    """Tests for SearchIndex context manager."""

    def test_context_manager_works(self, search_db_path):
        """Should work correctly as a context manager."""
        with SearchIndex(search_db_path) as index:
            index.index_learning(
                learning_id="ctx-learning-1",
                category="discovery",
                content="Context manager test learning about databases",
                confidence=0.7,
            )

            results = index.search("databases")

            assert len(results) >= 1
            assert results[0].learning_id == "ctx-learning-1"

        # After context manager exit, connection should be closed
        # Creating a new index should still be able to read the data
        with SearchIndex(search_db_path) as index2:
            results = index2.search("databases")
            assert len(results) >= 1

    def test_context_manager_closes_connection(self, search_db_path):
        """Should close the connection when exiting context."""
        index = SearchIndex(search_db_path)

        with index:
            assert index._connection is not None

        # After exiting, connection should be None
        assert index._connection is None
