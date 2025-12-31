"""Tests for the Ledger class."""

import pytest
from pathlib import Path

from claude_cortex.ledger import Ledger, Learning, LearningCategory, compute_content_hash


class TestLedgerAppendBlock:
    """Tests for Ledger.append_block method."""

    def test_append_block_creates_block(self, ledger_path):
        """Should create a block with the given learnings."""
        ledger = Ledger(ledger_path)

        learning = Learning(
            category=LearningCategory.DISCOVERY,
            content="Python uses indentation for code blocks",
            confidence=0.7,
        )

        block = ledger.append_block(
            session_id="test-session-1",
            learnings=[learning],
            deduplicate=False,
        )

        assert block is not None
        assert block.session_id == "test-session-1"
        assert len(block.learnings) == 1
        assert block.learnings[0].content == "Python uses indentation for code blocks"

    def test_append_block_updates_head(self, ledger_path):
        """Should update the ledger head to the new block."""
        ledger = Ledger(ledger_path)

        learning = Learning(
            category=LearningCategory.PATTERN,
            content="Use fixtures for test setup in pytest",
            confidence=0.6,
        )

        block = ledger.append_block(
            session_id="test-session-2",
            learnings=[learning],
            deduplicate=False,
        )

        assert ledger.get_head() == block.id

    def test_append_block_chains_correctly(self, ledger_path):
        """Should chain blocks with parent references."""
        ledger = Ledger(ledger_path)

        learning1 = Learning(
            category=LearningCategory.DISCOVERY,
            content="First learning about the project structure",
        )
        learning2 = Learning(
            category=LearningCategory.DECISION,
            content="Second learning about architecture decisions",
        )

        block1 = ledger.append_block(
            session_id="session-1",
            learnings=[learning1],
            deduplicate=False,
        )
        block2 = ledger.append_block(
            session_id="session-2",
            learnings=[learning2],
            deduplicate=False,
        )

        assert block1.parent_block is None
        assert block2.parent_block == block1.id


class TestLedgerGetLearningById:
    """Tests for Ledger.get_learning_by_id method."""

    def test_get_learning_by_id_retrieves_correctly(self, ledger_path):
        """Should retrieve a learning by its full ID."""
        ledger = Ledger(ledger_path)

        learning = Learning(
            category=LearningCategory.ERROR,
            content="Always check for None before accessing attributes",
            confidence=0.8,
        )

        block = ledger.append_block(
            session_id="test-session",
            learnings=[learning],
            deduplicate=False,
        )

        retrieved_learning, retrieved_block = ledger.get_learning_by_id(
            learning.id, prefix_match=False
        )

        assert retrieved_learning is not None
        assert retrieved_learning.id == learning.id
        assert retrieved_learning.content == learning.content
        assert retrieved_block.id == block.id

    def test_get_learning_by_id_prefix_match(self, ledger_path):
        """Should retrieve a learning by ID prefix."""
        ledger = Ledger(ledger_path)

        learning = Learning(
            category=LearningCategory.PATTERN,
            content="Use dependency injection for better testability",
        )

        ledger.append_block(
            session_id="test-session",
            learnings=[learning],
            deduplicate=False,
        )

        # Use first 8 characters as prefix
        prefix = learning.id[:8]
        retrieved_learning, _ = ledger.get_learning_by_id(prefix, prefix_match=True)

        assert retrieved_learning is not None
        assert retrieved_learning.id == learning.id

    def test_get_learning_by_id_not_found(self, ledger_path):
        """Should return None for non-existent learning ID."""
        ledger = Ledger(ledger_path)

        learning, block = ledger.get_learning_by_id(
            "non-existent-id", prefix_match=False
        )

        assert learning is None
        assert block is None


class TestLedgerFindByContentHash:
    """Tests for Ledger.find_by_content_hash method."""

    def test_find_by_content_hash_finds_duplicates(self, ledger_path):
        """Should find a learning by its content hash."""
        ledger = Ledger(ledger_path)

        content = "Use virtual environments for Python projects"
        learning = Learning(
            category=LearningCategory.PATTERN,
            content=content,
        )

        ledger.append_block(
            session_id="test-session",
            learnings=[learning],
            deduplicate=False,
        )

        content_hash = compute_content_hash(content)
        found_learning, found_id = ledger.find_by_content_hash(content_hash)

        assert found_learning is not None
        assert found_id == learning.id
        assert found_learning.content == content

    def test_find_by_content_hash_normalized_match(self, ledger_path):
        """Should find learning with normalized content matching."""
        ledger = Ledger(ledger_path)

        # Original content with specific casing
        original_content = "Use Type Hints in Python Functions"
        learning = Learning(
            category=LearningCategory.PATTERN,
            content=original_content,
        )

        ledger.append_block(
            session_id="test-session",
            learnings=[learning],
            deduplicate=False,
        )

        # Search with different casing/whitespace (normalized hash should match)
        search_content = "  use type hints  in python functions  "
        content_hash = compute_content_hash(search_content)
        found_learning, _ = ledger.find_by_content_hash(content_hash)

        assert found_learning is not None
        assert found_learning.id == learning.id

    def test_find_by_content_hash_not_found(self, ledger_path):
        """Should return None for non-existent content hash."""
        ledger = Ledger(ledger_path)

        content_hash = compute_content_hash("some content that does not exist")
        found_learning, found_id = ledger.find_by_content_hash(content_hash)

        assert found_learning is None
        assert found_id is None


class TestLedgerVerifyChain:
    """Tests for Ledger.verify_chain method."""

    def test_verify_chain_passes_for_valid_chain(self, ledger_path):
        """Should verify a valid chain successfully."""
        ledger = Ledger(ledger_path)

        learning1 = Learning(
            category=LearningCategory.DISCOVERY,
            content="First discovery about the codebase structure",
        )
        learning2 = Learning(
            category=LearningCategory.DECISION,
            content="Second decision about the architecture approach",
        )
        learning3 = Learning(
            category=LearningCategory.PATTERN,
            content="Third pattern identified in the code",
        )

        ledger.append_block(
            session_id="session-1",
            learnings=[learning1],
            deduplicate=False,
        )
        ledger.append_block(
            session_id="session-2",
            learnings=[learning2],
            deduplicate=False,
        )
        ledger.append_block(
            session_id="session-3",
            learnings=[learning3],
            deduplicate=False,
        )

        is_valid, errors = ledger.verify_chain()

        assert is_valid is True
        assert len(errors) == 0

    def test_verify_chain_empty_ledger(self, ledger_path):
        """Should verify an empty ledger successfully."""
        ledger = Ledger(ledger_path)

        is_valid, errors = ledger.verify_chain()

        assert is_valid is True
        assert len(errors) == 0
