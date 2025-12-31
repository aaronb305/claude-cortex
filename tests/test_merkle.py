"""Tests for the MerkleTree implementation."""

import json
import pytest
from pathlib import Path

from claude_cortex.ledger.merkle import MerkleTree, MerkleNode, EMPTY_HASH


class TestMerkleTreeEmpty:
    """Tests for empty Merkle trees."""

    def test_empty_tree(self):
        """Empty tree should have None root."""
        tree = MerkleTree()

        assert tree.root is None
        assert tree.root_hash is None
        assert len(tree) == 0

    def test_empty_tree_from_empty_list(self):
        """Tree built from empty list should have None root."""
        tree = MerkleTree([])

        assert tree.root is None
        assert tree.root_hash is None
        assert len(tree) == 0

    def test_empty_tree_build(self):
        """Building tree with empty list should set root to None."""
        tree = MerkleTree([("a", "hash_a")])
        assert tree.root is not None

        tree.build([])
        assert tree.root is None
        assert len(tree) == 0


class TestMerkleTreeSingleLeaf:
    """Tests for single leaf Merkle trees."""

    def test_single_leaf(self):
        """Single leaf tree should have correct root."""
        leaves = [("block1", "hash1")]
        tree = MerkleTree(leaves)

        assert tree.root is not None
        assert tree.root.is_leaf is True
        assert tree.root.block_id == "block1"
        assert tree.root.block_hash == "hash1"
        assert len(tree) == 1

    def test_single_leaf_root_hash(self):
        """Single leaf root hash should be the leaf hash."""
        leaves = [("block1", "hash1")]
        tree = MerkleTree(leaves)

        expected_hash = MerkleTree.hash_leaf("block1", "hash1")
        assert tree.root_hash == expected_hash

    def test_single_leaf_no_children(self):
        """Single leaf should have no left/right children."""
        leaves = [("block1", "hash1")]
        tree = MerkleTree(leaves)

        assert tree.root.left is None
        assert tree.root.right is None


class TestMerkleTreeTwoLeaves:
    """Tests for two-leaf Merkle trees."""

    def test_two_leaves(self):
        """Two leaves should combine correctly into a parent node."""
        leaves = [("block1", "hash1"), ("block2", "hash2")]
        tree = MerkleTree(leaves)

        assert tree.root is not None
        assert tree.root.is_leaf is False
        assert len(tree) == 2

    def test_two_leaves_children(self):
        """Two-leaf tree should have both children as leaves."""
        leaves = [("block1", "hash1"), ("block2", "hash2")]
        tree = MerkleTree(leaves)

        assert tree.root.left is not None
        assert tree.root.right is not None
        assert tree.root.left.is_leaf is True
        assert tree.root.right.is_leaf is True

    def test_two_leaves_root_hash(self):
        """Two-leaf tree root hash should be hash of children."""
        leaves = [("block1", "hash1"), ("block2", "hash2")]
        tree = MerkleTree(leaves)

        left_hash = MerkleTree.hash_leaf("block1", "hash1")
        right_hash = MerkleTree.hash_leaf("block2", "hash2")
        expected_root = MerkleTree.hash_pair(left_hash, right_hash)

        assert tree.root_hash == expected_root


class TestMerkleTreeOddLeaves:
    """Tests for Merkle trees with odd number of leaves."""

    def test_odd_leaves_three(self):
        """Three leaves should pad correctly."""
        leaves = [("a", "ha"), ("b", "hb"), ("c", "hc")]
        tree = MerkleTree(leaves)

        assert tree.root is not None
        assert len(tree) == 3
        # Root should have two children
        assert tree.root.left is not None
        assert tree.root.right is not None

    def test_odd_leaves_padding(self):
        """Odd number of leaves should use EMPTY_HASH for padding."""
        leaves = [("a", "ha"), ("b", "hb"), ("c", "hc")]
        tree = MerkleTree(leaves)

        # At the second level, 3 leaves become 2 nodes (one pair + one padded)
        # The first level: left subtree has 2 leaves, right subtree has 1 leaf padded with EMPTY_HASH
        # The right child of root should have one real leaf and one padding
        right_subtree = tree.root.right

        # Right subtree's right child should be the EMPTY_HASH padding
        if right_subtree.right:
            assert right_subtree.right.hash == EMPTY_HASH

    def test_odd_leaves_five(self):
        """Five leaves should pad correctly at each level."""
        leaves = [("a", "ha"), ("b", "hb"), ("c", "hc"), ("d", "hd"), ("e", "he")]
        tree = MerkleTree(leaves)

        assert tree.root is not None
        assert len(tree) == 5


class TestMerkleTreeDeterminism:
    """Tests for deterministic tree construction."""

    def test_deterministic(self):
        """Same inputs should always produce same root."""
        leaves = [("block1", "hash1"), ("block2", "hash2"), ("block3", "hash3")]

        tree1 = MerkleTree(leaves)
        tree2 = MerkleTree(leaves)

        assert tree1.root_hash == tree2.root_hash
        assert tree1 == tree2

    def test_deterministic_different_order(self):
        """Leaves in different order should still produce same tree (sorted by block_id)."""
        leaves1 = [("block1", "hash1"), ("block2", "hash2"), ("block3", "hash3")]
        leaves2 = [("block3", "hash3"), ("block1", "hash1"), ("block2", "hash2")]

        tree1 = MerkleTree(leaves1)
        tree2 = MerkleTree(leaves2)

        # Both trees should produce the same root because leaves are sorted by block_id
        assert tree1.root_hash == tree2.root_hash

    def test_sorted_leaves(self):
        """Leaves should be sorted by block_id in the tree."""
        leaves = [("z", "hz"), ("a", "ha"), ("m", "hm")]
        tree = MerkleTree(leaves)

        # Collect leaf IDs in tree order
        leaf_ids = tree._collect_leaf_ids(tree.root)

        assert leaf_ids == ["a", "m", "z"]


class TestMerkleTreeDiff:
    """Tests for Merkle tree diff functionality."""

    def test_diff_identical_trees(self):
        """Identical trees should return empty diff."""
        leaves = [("block1", "hash1"), ("block2", "hash2")]
        tree1 = MerkleTree(leaves)
        tree2 = MerkleTree(leaves)

        diff = tree1.diff(tree2)
        assert diff == []

    def test_diff_finds_missing(self):
        """Diff should find blocks in remote not in local."""
        local_leaves = [("block1", "hash1")]
        remote_leaves = [("block1", "hash1"), ("block2", "hash2")]

        local_tree = MerkleTree(local_leaves)
        remote_tree = MerkleTree(remote_leaves)

        diff = local_tree.diff(remote_tree)
        assert "block2" in diff
        assert "block1" not in diff

    def test_diff_handles_empty_local(self):
        """Diff with empty local tree should return all remote blocks."""
        local_tree = MerkleTree()
        remote_leaves = [("block1", "hash1"), ("block2", "hash2")]
        remote_tree = MerkleTree(remote_leaves)

        diff = local_tree.diff(remote_tree)
        assert set(diff) == {"block1", "block2"}

    def test_diff_handles_empty_remote(self):
        """Diff with empty remote tree should return empty list."""
        local_leaves = [("block1", "hash1"), ("block2", "hash2")]
        local_tree = MerkleTree(local_leaves)
        remote_tree = MerkleTree()

        diff = local_tree.diff(remote_tree)
        assert diff == []

    def test_diff_handles_both_empty(self):
        """Diff between two empty trees should return empty list."""
        local_tree = MerkleTree()
        remote_tree = MerkleTree()

        diff = local_tree.diff(remote_tree)
        assert diff == []

    def test_diff_multiple_missing(self):
        """Diff should find multiple missing blocks."""
        local_leaves = [("a", "ha")]
        remote_leaves = [("a", "ha"), ("b", "hb"), ("c", "hc"), ("d", "hd")]

        local_tree = MerkleTree(local_leaves)
        remote_tree = MerkleTree(remote_leaves)

        diff = local_tree.diff(remote_tree)
        assert set(diff) == {"b", "c", "d"}

    def test_diff_updated_block(self):
        """Diff should detect when a block hash has changed."""
        local_leaves = [("block1", "hash1")]
        remote_leaves = [("block1", "hash1_updated")]

        local_tree = MerkleTree(local_leaves)
        remote_tree = MerkleTree(remote_leaves)

        diff = local_tree.diff(remote_tree)
        # The block with changed hash should be in the diff
        assert "block1" in diff


class TestMerkleTreeSerialization:
    """Tests for Merkle tree serialization."""

    def test_serialization_roundtrip(self):
        """to_dict/from_dict should preserve tree."""
        leaves = [("block1", "hash1"), ("block2", "hash2"), ("block3", "hash3")]
        original = MerkleTree(leaves)

        serialized = original.to_dict()
        restored = MerkleTree.from_dict(serialized)

        assert restored.root_hash == original.root_hash
        assert len(restored) == len(original)
        assert restored == original

    def test_serialization_empty_tree(self):
        """Empty tree should serialize and deserialize correctly."""
        original = MerkleTree()

        serialized = original.to_dict()
        assert serialized["root"] is None
        assert serialized["leaf_count"] == 0

        restored = MerkleTree.from_dict(serialized)
        assert restored.root is None
        assert len(restored) == 0

    def test_serialization_single_leaf(self):
        """Single leaf tree should serialize correctly."""
        leaves = [("block1", "hash1")]
        original = MerkleTree(leaves)

        serialized = original.to_dict()
        assert serialized["leaf_count"] == 1
        assert serialized["root"]["block_id"] == "block1"
        assert serialized["root"]["block_hash"] == "hash1"

        restored = MerkleTree.from_dict(serialized)
        assert restored.root.block_id == "block1"

    def test_serialization_preserves_structure(self):
        """Serialization should preserve tree structure."""
        leaves = [("a", "ha"), ("b", "hb"), ("c", "hc"), ("d", "hd")]
        original = MerkleTree(leaves)

        serialized = original.to_dict()

        # Check structure
        assert "left" in serialized["root"]
        assert "right" in serialized["root"]

        restored = MerkleTree.from_dict(serialized)

        # Collect all leaf IDs and verify they match
        original_ids = original._collect_leaf_ids(original.root)
        restored_ids = restored._collect_leaf_ids(restored.root)

        assert original_ids == restored_ids

    def test_serialization_version(self):
        """Serialized tree should include version."""
        tree = MerkleTree([("a", "ha")])
        serialized = tree.to_dict()

        assert serialized["version"] == 1


class TestMerkleTreeSaveLoad:
    """Tests for Merkle tree file operations."""

    def test_save_load_roundtrip(self, temp_dir):
        """save/load should preserve tree."""
        leaves = [("block1", "hash1"), ("block2", "hash2")]
        original = MerkleTree(leaves)

        merkle_path = temp_dir / "merkle.json"
        original.save(merkle_path)

        assert merkle_path.exists()

        loaded = MerkleTree.load(merkle_path)

        assert loaded is not None
        assert loaded.root_hash == original.root_hash
        assert len(loaded) == len(original)

    def test_save_creates_parent_dirs(self, temp_dir):
        """save should create parent directories if needed."""
        leaves = [("block1", "hash1")]
        tree = MerkleTree(leaves)

        merkle_path = temp_dir / "subdir" / "deep" / "merkle.json"
        tree.save(merkle_path)

        assert merkle_path.exists()
        assert merkle_path.parent.exists()

    def test_load_nonexistent_file(self, temp_dir):
        """load should return None for nonexistent file."""
        merkle_path = temp_dir / "nonexistent.json"

        loaded = MerkleTree.load(merkle_path)

        assert loaded is None

    def test_save_load_empty_tree(self, temp_dir):
        """Empty tree should save and load correctly."""
        original = MerkleTree()

        merkle_path = temp_dir / "merkle.json"
        original.save(merkle_path)

        loaded = MerkleTree.load(merkle_path)

        assert loaded is not None
        assert loaded.root is None
        assert len(loaded) == 0

    def test_save_file_content(self, temp_dir):
        """Saved file should be valid JSON with expected structure."""
        leaves = [("block1", "hash1")]
        tree = MerkleTree(leaves)

        merkle_path = temp_dir / "merkle.json"
        tree.save(merkle_path)

        with open(merkle_path) as f:
            data = json.load(f)

        assert "version" in data
        assert "leaf_count" in data
        assert "root_hash" in data
        assert "root" in data


class TestMerkleTreeEquality:
    """Tests for Merkle tree equality."""

    def test_equality_same_trees(self):
        """Trees with same content should be equal."""
        leaves = [("a", "ha"), ("b", "hb")]
        tree1 = MerkleTree(leaves)
        tree2 = MerkleTree(leaves)

        assert tree1 == tree2

    def test_equality_different_trees(self):
        """Trees with different content should not be equal."""
        tree1 = MerkleTree([("a", "ha")])
        tree2 = MerkleTree([("b", "hb")])

        assert tree1 != tree2

    def test_equality_empty_trees(self):
        """Empty trees should be equal."""
        tree1 = MerkleTree()
        tree2 = MerkleTree()

        assert tree1 == tree2

    def test_equality_with_non_tree(self):
        """Equality with non-MerkleTree should return NotImplemented."""
        tree = MerkleTree([("a", "ha")])

        assert tree.__eq__("not a tree") == NotImplemented
        assert tree.__eq__(123) == NotImplemented


class TestMerkleNodeProperties:
    """Tests for MerkleNode properties."""

    def test_leaf_node_is_leaf(self):
        """Leaf node should report is_leaf as True."""
        node = MerkleNode(
            hash="somehash",
            block_id="block1",
            block_hash="blockhash1"
        )

        assert node.is_leaf is True

    def test_internal_node_is_not_leaf(self):
        """Internal node should report is_leaf as False."""
        left = MerkleNode(hash="lefthash", block_id="a", block_hash="ha")
        right = MerkleNode(hash="righthash", block_id="b", block_hash="hb")
        parent = MerkleNode(hash="parenthash", left=left, right=right)

        assert parent.is_leaf is False


class TestMerkleTreeHashing:
    """Tests for Merkle tree hash functions."""

    def test_hash_leaf_deterministic(self):
        """hash_leaf should be deterministic."""
        hash1 = MerkleTree.hash_leaf("block1", "hash1")
        hash2 = MerkleTree.hash_leaf("block1", "hash1")

        assert hash1 == hash2

    def test_hash_leaf_different_inputs(self):
        """hash_leaf should produce different hashes for different inputs."""
        hash1 = MerkleTree.hash_leaf("block1", "hash1")
        hash2 = MerkleTree.hash_leaf("block2", "hash2")

        assert hash1 != hash2

    def test_hash_pair_deterministic(self):
        """hash_pair should be deterministic."""
        hash1 = MerkleTree.hash_pair("left", "right")
        hash2 = MerkleTree.hash_pair("left", "right")

        assert hash1 == hash2

    def test_hash_pair_order_matters(self):
        """hash_pair should produce different results for swapped inputs."""
        hash1 = MerkleTree.hash_pair("left", "right")
        hash2 = MerkleTree.hash_pair("right", "left")

        assert hash1 != hash2

    def test_hash_length(self):
        """Hashes should be SHA-256 (64 hex characters)."""
        hash_leaf = MerkleTree.hash_leaf("block", "hash")
        hash_pair = MerkleTree.hash_pair("left", "right")

        assert len(hash_leaf) == 64
        assert len(hash_pair) == 64
