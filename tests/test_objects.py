"""Tests for the content-addressed ObjectStore."""

import pytest
from pathlib import Path

from continuous_claude.ledger.objects import ObjectStore, compute_content_hash


class TestComputeContentHash:
    """Tests for the compute_content_hash function."""

    def test_compute_content_hash_deterministic(self):
        """Same content always produces same hash."""
        content = "This is a test learning about Python patterns"

        hash1 = compute_content_hash(content)
        hash2 = compute_content_hash(content)
        hash3 = compute_content_hash(content)

        assert hash1 == hash2
        assert hash2 == hash3

    def test_compute_content_hash_normalized(self):
        """Different whitespace/case produces same hash."""
        # Original content
        content1 = "Use Type Hints in Python Functions"

        # Different casing
        content2 = "use type hints in python functions"

        # Extra whitespace
        content3 = "  use type hints  in python functions  "

        # Multiple spaces and tabs
        content4 = "USE\tTYPE  HINTS\n\nIN   PYTHON FUNCTIONS"

        hash1 = compute_content_hash(content1)
        hash2 = compute_content_hash(content2)
        hash3 = compute_content_hash(content3)
        hash4 = compute_content_hash(content4)

        assert hash1 == hash2
        assert hash2 == hash3
        assert hash3 == hash4

    def test_compute_content_hash_different_content(self):
        """Different content produces different hashes."""
        content1 = "First unique content about Python"
        content2 = "Second completely different content"

        hash1 = compute_content_hash(content1)
        hash2 = compute_content_hash(content2)

        assert hash1 != hash2

    def test_compute_content_hash_returns_16_chars(self):
        """Hash is 16-character hex string (first 16 chars of SHA-256)."""
        content = "Test content for hash length"

        content_hash = compute_content_hash(content)

        assert len(content_hash) == 16
        assert all(c in '0123456789abcdef' for c in content_hash)


class TestObjectStoreBasics:
    """Tests for basic ObjectStore operations."""

    def test_store_learning(self, temp_dir):
        """Store returns content hash."""
        store = ObjectStore(temp_dir / "objects")
        content = "Python uses indentation for code blocks"

        content_hash = store.store(content)

        assert content_hash is not None
        assert len(content_hash) == 16
        assert content_hash == compute_content_hash(content)

    def test_store_deduplicates(self, temp_dir):
        """Storing same content twice returns same hash, only one file."""
        store = ObjectStore(temp_dir / "objects")
        content = "Use virtual environments for Python projects"

        hash1 = store.store(content)
        hash2 = store.store(content)

        # Same hash returned
        assert hash1 == hash2

        # Only one file should exist
        all_hashes = store.list_all()
        assert len(all_hashes) == 1
        assert hash1 in all_hashes

    def test_store_normalized_deduplicates(self, temp_dir):
        """Storing normalized-equivalent content returns same hash."""
        store = ObjectStore(temp_dir / "objects")

        content1 = "Use Type Hints in Python"
        content2 = "  USE  TYPE  HINTS  IN  PYTHON  "

        hash1 = store.store(content1)
        hash2 = store.store(content2)

        # Same hash due to normalization
        assert hash1 == hash2

        # Only one file stored
        assert len(store.list_all()) == 1

    def test_get_existing(self, temp_dir):
        """Can retrieve stored learning."""
        store = ObjectStore(temp_dir / "objects")
        content = "Always check for None before accessing attributes"

        content_hash = store.store(content)
        retrieved = store.get(content_hash)

        assert retrieved is not None
        assert retrieved == content

    def test_get_nonexistent(self, temp_dir):
        """Returns None for unknown hash."""
        store = ObjectStore(temp_dir / "objects")

        # Try to get a hash that doesn't exist (16 chars)
        result = store.get("0123456789abcdef")

        assert result is None

    def test_exists(self, temp_dir):
        """Correctly reports object existence."""
        store = ObjectStore(temp_dir / "objects")
        content = "Use fixtures for test setup in pytest"

        # Before storing
        content_hash = compute_content_hash(content)
        assert store.exists(content_hash) is False

        # After storing
        store.store(content)
        assert store.exists(content_hash) is True

        # Non-existent hash
        assert store.exists("fedcba9876543210") is False

    def test_list_all(self, temp_dir):
        """Lists all stored hashes."""
        store = ObjectStore(temp_dir / "objects")

        # Initially empty
        assert store.list_all() == []

        # Store multiple items
        content1 = "First learning about project structure"
        content2 = "Second learning about architecture"
        content3 = "Third learning about testing"

        hash1 = store.store(content1)
        hash2 = store.store(content2)
        hash3 = store.store(content3)

        all_hashes = store.list_all()

        assert len(all_hashes) == 3
        assert hash1 in all_hashes
        assert hash2 in all_hashes
        assert hash3 in all_hashes


class TestObjectStoreDelete:
    """Tests for ObjectStore delete operations."""

    def test_delete(self, temp_dir):
        """Can delete objects."""
        store = ObjectStore(temp_dir / "objects")
        content = "Temporary learning to be deleted"

        content_hash = store.store(content)
        assert store.exists(content_hash) is True

        # Delete
        result = store.delete(content_hash)

        assert result is True
        assert store.exists(content_hash) is False
        assert store.get(content_hash) is None

    def test_delete_nonexistent(self, temp_dir):
        """Deleting non-existent object returns False."""
        store = ObjectStore(temp_dir / "objects")

        result = store.delete("abcdef1234567890")

        assert result is False


class TestObjectStoreGarbageCollection:
    """Tests for ObjectStore garbage collection."""

    def test_gc_removes_unreferenced(self, temp_dir):
        """GC removes objects not in referenced set."""
        store = ObjectStore(temp_dir / "objects")

        # Store several items
        content1 = "Referenced learning one"
        content2 = "Unreferenced learning two"
        content3 = "Referenced learning three"
        content4 = "Unreferenced learning four"

        hash1 = store.store(content1)
        hash2 = store.store(content2)
        hash3 = store.store(content3)
        hash4 = store.store(content4)

        # Only reference hash1 and hash3
        referenced = {hash1, hash3}

        # Run garbage collection
        removed_count = store.gc(referenced)

        assert removed_count == 2
        assert store.exists(hash1) is True
        assert store.exists(hash2) is False
        assert store.exists(hash3) is True
        assert store.exists(hash4) is False

    def test_gc_keeps_referenced(self, temp_dir):
        """GC keeps objects in referenced set."""
        store = ObjectStore(temp_dir / "objects")

        # Store items
        content1 = "Keep this learning"
        content2 = "Keep this one too"

        hash1 = store.store(content1)
        hash2 = store.store(content2)

        # Reference all items
        referenced = {hash1, hash2}

        # Run garbage collection
        removed_count = store.gc(referenced)

        assert removed_count == 0
        assert store.exists(hash1) is True
        assert store.exists(hash2) is True
        assert len(store.list_all()) == 2

    def test_gc_empty_store(self, temp_dir):
        """GC on empty store removes nothing."""
        store = ObjectStore(temp_dir / "objects")

        removed_count = store.gc(set())

        assert removed_count == 0

    def test_gc_all_unreferenced(self, temp_dir):
        """GC removes all objects when none are referenced."""
        store = ObjectStore(temp_dir / "objects")

        store.store("Orphan learning 1")
        store.store("Orphan learning 2")
        store.store("Orphan learning 3")

        # Empty referenced set
        removed_count = store.gc(set())

        assert removed_count == 3
        assert len(store.list_all()) == 0


class TestObjectStoreDirectorySharding:
    """Tests for directory sharding in ObjectStore."""

    def test_directory_sharding(self, temp_dir):
        """Objects stored in prefix directories."""
        store = ObjectStore(temp_dir / "objects")
        content = "Learning with specific hash for sharding test"

        content_hash = store.store(content)

        # Objects should be stored in subdirectories based on first 2 chars of hash
        prefix = content_hash[:2]
        expected_dir = temp_dir / "objects" / prefix
        expected_file = expected_dir / f"{content_hash}.json"

        assert expected_dir.exists()
        assert expected_dir.is_dir()
        assert expected_file.exists()

    def test_directory_sharding_multiple_prefixes(self, temp_dir):
        """Multiple objects create multiple prefix directories."""
        store = ObjectStore(temp_dir / "objects")

        # Store several items - they should land in different prefix directories
        contents = [
            "First learning for sharding",
            "Second learning for sharding",
            "Third learning for sharding",
            "Fourth learning for sharding",
            "Fifth learning for sharding",
        ]

        hashes = [store.store(c) for c in contents]
        prefixes = {h[:2] for h in hashes}

        # Each prefix should have its own directory
        for prefix in prefixes:
            prefix_dir = temp_dir / "objects" / prefix
            assert prefix_dir.exists()
            assert prefix_dir.is_dir()

    def test_directory_sharding_retrieval(self, temp_dir):
        """Can retrieve objects stored in sharded directories."""
        store = ObjectStore(temp_dir / "objects")

        contents = [
            "Retrievable learning alpha",
            "Retrievable learning beta",
            "Retrievable learning gamma",
        ]

        hashes = [store.store(c) for c in contents]

        # All should be retrievable
        for i, h in enumerate(hashes):
            retrieved = store.get(h)
            assert retrieved == contents[i]


class TestObjectStoreEdgeCases:
    """Tests for edge cases in ObjectStore."""

    def test_empty_content(self, temp_dir):
        """Handle empty content string."""
        store = ObjectStore(temp_dir / "objects")

        content_hash = store.store("")

        assert content_hash is not None
        assert store.exists(content_hash)
        assert store.get(content_hash) == ""

    def test_whitespace_only_content(self, temp_dir):
        """Handle whitespace-only content."""
        store = ObjectStore(temp_dir / "objects")

        # Different whitespace patterns should normalize to same hash
        hash1 = store.store("   ")
        hash2 = store.store("\t\n")
        hash3 = store.store("  \n\t  ")

        assert hash1 == hash2
        assert hash2 == hash3

    def test_unicode_content(self, temp_dir):
        """Handle unicode content."""
        store = ObjectStore(temp_dir / "objects")
        content = "Unicode content: eee zhongwen Russkij"

        content_hash = store.store(content)
        retrieved = store.get(content_hash)

        assert retrieved == content

    def test_large_content(self, temp_dir):
        """Handle large content."""
        store = ObjectStore(temp_dir / "objects")
        content = "x" * 100000  # 100KB of content

        content_hash = store.store(content)
        retrieved = store.get(content_hash)

        assert retrieved == content

    def test_special_characters(self, temp_dir):
        """Handle special characters in content."""
        store = ObjectStore(temp_dir / "objects")
        content = 'Special chars: <>&"\'\\/:*?|'

        content_hash = store.store(content)
        retrieved = store.get(content_hash)

        assert retrieved == content

    def test_newlines_preserved(self, temp_dir):
        """Content with newlines is stored correctly."""
        store = ObjectStore(temp_dir / "objects")
        content = "Line 1\nLine 2\nLine 3"

        content_hash = store.store(content)
        retrieved = store.get(content_hash)

        assert retrieved == content

    def test_store_creates_directory(self, temp_dir):
        """Store creates the objects directory if it doesn't exist."""
        objects_path = temp_dir / "new_objects_dir"
        assert not objects_path.exists()

        store = ObjectStore(objects_path)
        store.store("Test content")

        assert objects_path.exists()
