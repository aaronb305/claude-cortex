"""Merkle tree implementation for efficient ledger sync."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# Constant for padding odd levels
EMPTY_HASH = hashlib.sha256(b"").hexdigest()


@dataclass
class MerkleNode:
    """A node in the Merkle tree."""

    hash: str
    left: Optional["MerkleNode"] = None
    right: Optional["MerkleNode"] = None
    # For leaf nodes only
    block_id: Optional[str] = None
    block_hash: Optional[str] = None

    @property
    def is_leaf(self) -> bool:
        """Check if this is a leaf node."""
        return self.block_id is not None


@dataclass
class MerkleTree:
    """Binary Merkle tree for efficient ledger diffing."""

    root: Optional[MerkleNode] = field(default=None)
    _leaf_count: int = field(default=0, repr=False)

    def __init__(self, leaves: Optional[list[tuple[str, str]]] = None):
        """
        Initialize tree from list of (block_id, block_hash) tuples.
        Leaves should be sorted by block_id for deterministic trees.

        Args:
            leaves: List of (block_id, block_hash) tuples. If None, creates empty tree.
        """
        self.root = None
        self._leaf_count = 0
        if leaves:
            self.build(leaves)

    @property
    def root_hash(self) -> Optional[str]:
        """Get the root hash of the tree."""
        if self.root is None:
            return None
        return self.root.hash

    def build(self, leaves: list[tuple[str, str]]) -> None:
        """
        Build the tree from sorted leaves.

        Args:
            leaves: List of (block_id, block_hash) tuples, should be sorted by block_id
        """
        if not leaves:
            self.root = None
            self._leaf_count = 0
            return

        # Sort leaves by block_id for deterministic trees
        sorted_leaves = sorted(leaves, key=lambda x: x[0])
        self._leaf_count = len(sorted_leaves)

        # Create leaf nodes
        nodes: list[MerkleNode] = []
        for block_id, block_hash in sorted_leaves:
            leaf_hash = self.hash_leaf(block_id, block_hash)
            nodes.append(
                MerkleNode(
                    hash=leaf_hash,
                    block_id=block_id,
                    block_hash=block_hash,
                )
            )

        # Build tree bottom-up
        while len(nodes) > 1:
            next_level: list[MerkleNode] = []

            # Process pairs
            for i in range(0, len(nodes), 2):
                left = nodes[i]
                # Pad with empty hash if odd number of nodes
                if i + 1 < len(nodes):
                    right = nodes[i + 1]
                else:
                    right = MerkleNode(hash=EMPTY_HASH)

                parent_hash = self.hash_pair(left.hash, right.hash)
                parent = MerkleNode(hash=parent_hash, left=left, right=right)
                next_level.append(parent)

            nodes = next_level

        self.root = nodes[0] if nodes else None

    @staticmethod
    def hash_leaf(block_id: str, block_hash: str) -> str:
        """
        Hash a leaf node.

        Args:
            block_id: The block's unique identifier
            block_hash: The block's content hash

        Returns:
            SHA-256 hash of the combined block_id and block_hash
        """
        content = f"leaf:{block_id}:{block_hash}"
        return hashlib.sha256(content.encode()).hexdigest()

    @staticmethod
    def hash_pair(left_hash: str, right_hash: str) -> str:
        """
        Hash two child hashes to create parent.

        Args:
            left_hash: Hash of the left child
            right_hash: Hash of the right child

        Returns:
            SHA-256 hash of the concatenated child hashes
        """
        content = f"{left_hash}:{right_hash}"
        return hashlib.sha256(content.encode()).hexdigest()

    def diff(self, other: "MerkleTree") -> list[str]:
        """
        Find block_ids that exist in other but not in self.
        Returns list of block_ids to fetch from other.
        Uses O(log n) comparison when trees share structure.

        Args:
            other: The other MerkleTree to compare against

        Returns:
            List of block_ids present in other but not in self
        """
        if other.root is None:
            return []

        if self.root is None:
            # Self is empty, return all blocks from other
            return self._collect_leaf_ids(other.root)

        if self.root.hash == other.root.hash:
            # Trees are identical
            return []

        # Recursively find differences
        return self._diff_nodes(self.root, other.root)

    def _diff_nodes(
        self, self_node: Optional[MerkleNode], other_node: Optional[MerkleNode]
    ) -> list[str]:
        """
        Recursively compare nodes to find differences.

        Args:
            self_node: Node from self tree (may be None)
            other_node: Node from other tree (may be None)

        Returns:
            List of block_ids in other but not in self
        """
        # If other has nothing, nothing to fetch
        if other_node is None:
            return []

        # If self has nothing, fetch everything from other
        if self_node is None:
            return self._collect_leaf_ids(other_node)

        # If hashes match, subtrees are identical
        if self_node.hash == other_node.hash:
            return []

        # If other is a leaf, it's different
        if other_node.is_leaf:
            # Check if self has this exact block
            if self_node.is_leaf:
                if self_node.block_id == other_node.block_id:
                    # Same block, different hash = updated block
                    # For now, treat as needing to fetch
                    return [other_node.block_id]
                else:
                    # Different blocks entirely
                    return [other_node.block_id]
            else:
                # other is leaf but self has subtree - check if leaf exists in subtree
                self_ids = set(self._collect_leaf_ids(self_node))
                if other_node.block_id not in self_ids:
                    return [other_node.block_id]
                return []

        # If self is a leaf but other is not, collect all from other that aren't self
        if self_node.is_leaf:
            other_ids = self._collect_leaf_ids(other_node)
            return [bid for bid in other_ids if bid != self_node.block_id]

        # Both are internal nodes - recurse into children
        result: list[str] = []
        result.extend(self._diff_nodes(self_node.left, other_node.left))
        result.extend(self._diff_nodes(self_node.right, other_node.right))

        return result

    def _collect_leaf_ids(self, node: Optional[MerkleNode]) -> list[str]:
        """
        Collect all block_ids from a subtree.

        Args:
            node: Root of the subtree

        Returns:
            List of all block_ids in the subtree
        """
        if node is None:
            return []

        if node.is_leaf:
            return [node.block_id]

        result: list[str] = []
        if node.left:
            result.extend(self._collect_leaf_ids(node.left))
        if node.right:
            result.extend(self._collect_leaf_ids(node.right))

        return result

    def to_dict(self) -> dict:
        """
        Serialize tree for storage in merkle.json.

        Returns:
            Dictionary representation of the tree
        """
        return {
            "version": 1,
            "leaf_count": self._leaf_count,
            "root_hash": self.root_hash,
            "root": self._node_to_dict(self.root) if self.root else None,
        }

    def _node_to_dict(self, node: MerkleNode) -> dict:
        """
        Serialize a node to dict.

        Args:
            node: The node to serialize

        Returns:
            Dictionary representation of the node
        """
        result = {"hash": node.hash}

        if node.is_leaf:
            result["block_id"] = node.block_id
            result["block_hash"] = node.block_hash
        else:
            if node.left:
                result["left"] = self._node_to_dict(node.left)
            if node.right:
                result["right"] = self._node_to_dict(node.right)

        return result

    @classmethod
    def from_dict(cls, data: dict) -> "MerkleTree":
        """
        Deserialize tree from merkle.json.

        Args:
            data: Dictionary representation from to_dict()

        Returns:
            Reconstructed MerkleTree instance
        """
        tree = cls()

        if data.get("root") is None:
            return tree

        tree._leaf_count = data.get("leaf_count", 0)
        tree.root = cls._node_from_dict(data["root"])

        return tree

    @classmethod
    def _node_from_dict(cls, data: dict) -> MerkleNode:
        """
        Deserialize a node from dict.

        Args:
            data: Dictionary representation of a node

        Returns:
            Reconstructed MerkleNode
        """
        node = MerkleNode(
            hash=data["hash"],
            block_id=data.get("block_id"),
            block_hash=data.get("block_hash"),
        )

        if "left" in data:
            node.left = cls._node_from_dict(data["left"])
        if "right" in data:
            node.right = cls._node_from_dict(data["right"])

        return node

    def save(self, path: Path) -> None:
        """
        Save tree to merkle.json file.

        Args:
            path: Path to save the merkle.json file
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=2)

    @classmethod
    def load(cls, path: Path) -> Optional["MerkleTree"]:
        """
        Load tree from merkle.json file.

        Args:
            path: Path to the merkle.json file

        Returns:
            Loaded MerkleTree, or None if file doesn't exist
        """
        if not path.exists():
            return None

        with open(path) as f:
            data = json.load(f)

        return cls.from_dict(data)

    def __eq__(self, other: object) -> bool:
        """Check equality by comparing root hashes."""
        if not isinstance(other, MerkleTree):
            return NotImplemented
        return self.root_hash == other.root_hash

    def __len__(self) -> int:
        """Return the number of leaves in the tree."""
        return self._leaf_count
