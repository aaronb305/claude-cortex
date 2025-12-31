"""Sync protocol for distributed ledger synchronization.

This module handles syncing between two ledgers (local and remote).
Currently supports local-to-local sync; SSH support is planned for future.
"""

from __future__ import annotations

import json
import shutil
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from .ledger import Block, Ledger, file_lock


class SyncStatus(Enum):
    """Status of sync between two ledgers."""

    IN_SYNC = "in_sync"
    LOCAL_AHEAD = "local_ahead"
    REMOTE_AHEAD = "remote_ahead"
    DIVERGED = "diverged"


@dataclass
class SyncResult:
    """Result of a sync operation."""

    status: SyncStatus
    blocks_imported: list[str] = field(default_factory=list)  # Block IDs imported from remote
    blocks_to_export: list[str] = field(default_factory=list)  # Block IDs remote doesn't have
    errors: list[str] = field(default_factory=list)


@dataclass
class SyncInfo:
    """Information about sync state."""

    local_root: Optional[str]
    remote_root: Optional[str]
    local_block_count: int
    remote_block_count: int
    status: SyncStatus
    missing_locally: list[str] = field(default_factory=list)  # Blocks we need from remote
    missing_remotely: list[str] = field(default_factory=list)  # Blocks remote needs from us


class LedgerSync:
    """Handles synchronization between two ledgers.

    Currently supports local file paths only. SSH paths (user@host:/path)
    are planned for future enhancement.
    """

    def __init__(self, local_path: Path, remote_path: Path):
        """Initialize sync between local and remote ledgers.

        Args:
            local_path: Path to local ledger directory
            remote_path: Path to remote ledger directory (local path only for now).
                        SSH paths (user@host:/path) are not yet supported.

        Raises:
            ValueError: If remote_path appears to be an SSH path
            NotADirectoryError: If paths don't exist or aren't directories
        """
        self.local_path = Path(local_path)
        self.remote_path = Path(remote_path)

        # Check for SSH path format (future enhancement)
        remote_str = str(remote_path)
        if '@' in remote_str and ':' in remote_str:
            raise ValueError(
                f"SSH paths not yet supported: {remote_str}. "
                "Use a local path or export/import for remote sync."
            )

        # Validate paths exist
        if not self.local_path.exists():
            raise NotADirectoryError(f"Local ledger path does not exist: {local_path}")
        if not self.remote_path.exists():
            raise NotADirectoryError(f"Remote ledger path does not exist: {remote_path}")

        # Initialize ledger instances
        self._local_ledger: Optional[Ledger] = None
        self._remote_ledger: Optional[Ledger] = None

    @property
    def local_ledger(self) -> Ledger:
        """Get or create the local ledger instance."""
        if self._local_ledger is None:
            self._local_ledger = Ledger(self.local_path)
        return self._local_ledger

    @property
    def remote_ledger(self) -> Ledger:
        """Get or create the remote ledger instance."""
        if self._remote_ledger is None:
            self._remote_ledger = Ledger(self.remote_path)
        return self._remote_ledger

    def _get_block_ids(self, ledger: Ledger) -> set[str]:
        """Get all block IDs from a ledger."""
        index = ledger._read_json(ledger.index_file)
        return {block_info["id"] for block_info in index.get("blocks", [])}

    def _get_block_chain(self, ledger: Ledger) -> list[str]:
        """Get block IDs in chain order (oldest first)."""
        index = ledger._read_json(ledger.index_file)
        return [block_info["id"] for block_info in index.get("blocks", [])]

    def _find_common_ancestor(self) -> Optional[str]:
        """Find the most recent common block between local and remote.

        Returns:
            Block ID of common ancestor, or None if chains share no history
        """
        local_chain = self._get_block_chain(self.local_ledger)
        remote_ids = self._get_block_ids(self.remote_ledger)

        # Walk backwards through local chain to find first match
        for block_id in reversed(local_chain):
            if block_id in remote_ids:
                return block_id

        return None

    def _determine_status(
        self,
        local_ids: set[str],
        remote_ids: set[str],
    ) -> SyncStatus:
        """Determine sync status based on block sets."""
        missing_locally = remote_ids - local_ids
        missing_remotely = local_ids - remote_ids

        if not missing_locally and not missing_remotely:
            return SyncStatus.IN_SYNC
        elif missing_locally and not missing_remotely:
            return SyncStatus.REMOTE_AHEAD
        elif missing_remotely and not missing_locally:
            return SyncStatus.LOCAL_AHEAD
        else:
            # Both have blocks the other doesn't
            # Check if chains diverged or just need bidirectional sync
            local_chain = self._get_block_chain(self.local_ledger)
            remote_chain = self._get_block_chain(self.remote_ledger)

            # If one chain is a prefix of the other, it's not diverged
            common_ancestor = self._find_common_ancestor()
            if common_ancestor:
                local_after = local_chain[local_chain.index(common_ancestor)+1:] if common_ancestor in local_chain else local_chain
                remote_after = remote_chain[remote_chain.index(common_ancestor)+1:] if common_ancestor in remote_chain else remote_chain

                # If both have blocks after the ancestor, they diverged
                if local_after and remote_after:
                    return SyncStatus.DIVERGED

            # No common ancestor means completely separate histories
            if not common_ancestor and local_ids and remote_ids:
                return SyncStatus.DIVERGED

            return SyncStatus.DIVERGED

    def get_sync_info(self) -> SyncInfo:
        """Compare local and remote ledgers without making changes.

        Returns:
            SyncInfo with details about what would be synced
        """
        local_ids = self._get_block_ids(self.local_ledger)
        remote_ids = self._get_block_ids(self.remote_ledger)

        missing_locally = list(remote_ids - local_ids)
        missing_remotely = list(local_ids - remote_ids)

        status = self._determine_status(local_ids, remote_ids)

        return SyncInfo(
            local_root=self.local_ledger.get_head(),
            remote_root=self.remote_ledger.get_head(),
            local_block_count=len(local_ids),
            remote_block_count=len(remote_ids),
            status=status,
            missing_locally=missing_locally,
            missing_remotely=missing_remotely,
        )

    def _verify_block(self, block_data: dict) -> bool:
        """Verify block hash matches content.

        Args:
            block_data: Raw block data dictionary from JSON file

        Returns:
            True if hash verification passes, False otherwise
        """
        stored_hash = block_data.get("hash")
        if not stored_hash:
            return False

        try:
            # Remove hash from data before recomputing
            # Block.model_validate ignores the stored hash (computed_field)
            # and computes fresh from content
            data_without_hash = {k: v for k, v in block_data.items() if k != "hash"}
            block = Block.model_validate(data_without_hash)
            return block.hash == stored_hash
        except Exception:
            return False

    def _import_block(self, block_data: dict, ledger: Ledger) -> bool:
        """Import a block into a ledger.

        Args:
            block_data: Raw block data dictionary
            ledger: Target ledger to import into

        Returns:
            True if import succeeded, False otherwise
        """
        try:
            block_id = block_data.get("id")
            if not block_id:
                return False

            block_file = ledger.blocks_dir / f"{block_id}.json"

            # Don't overwrite existing blocks
            if block_file.exists():
                return True

            # Write block file
            with file_lock(block_file, exclusive=True):
                with open(block_file, "w") as f:
                    json.dump(block_data, f, indent=2, default=str)

            return True
        except Exception:
            return False

    def _update_index(self, ledger: Ledger, new_blocks: list[dict]) -> bool:
        """Update ledger index with new blocks in correct order.

        Args:
            ledger: Ledger to update
            new_blocks: List of block data dicts to add to index

        Returns:
            True if update succeeded
        """
        if not new_blocks:
            return True

        try:
            with file_lock(ledger.index_file, exclusive=True):
                with open(ledger.index_file) as f:
                    index = json.load(f)

                existing_ids = {b["id"] for b in index.get("blocks", [])}

                # Sort new blocks by parent relationship to ensure correct order
                blocks_to_add = []
                for block_data in new_blocks:
                    block_id = block_data.get("id")
                    if block_id and block_id not in existing_ids:
                        blocks_to_add.append({
                            "id": block_id,
                            "timestamp": block_data.get("timestamp"),
                            "hash": block_data.get("hash"),
                            "parent": block_data.get("parent_block"),
                        })

                # Order blocks by parent chain
                ordered = self._order_by_parent(blocks_to_add, index.get("head"))

                # Add to index
                for block_info in ordered:
                    index["blocks"].append(block_info)
                    index["head"] = block_info["id"]

                with open(ledger.index_file, "w") as f:
                    json.dump(index, f, indent=2, default=str)

            return True
        except Exception:
            return False

    def _order_by_parent(
        self,
        blocks: list[dict],
        current_head: Optional[str],
    ) -> list[dict]:
        """Order blocks by parent relationship for correct chain insertion.

        Args:
            blocks: Blocks to order
            current_head: Current head of the target chain

        Returns:
            Blocks in order (parent before child)
        """
        if not blocks:
            return []

        # Build parent -> children mapping
        block_map = {b["id"]: b for b in blocks}
        ordered = []
        added = set()

        # Find blocks whose parent is current_head or already added
        def can_add(block: dict) -> bool:
            parent = block.get("parent")
            return parent == current_head or parent in added or parent is None

        # Iteratively add blocks in order
        max_iterations = len(blocks) + 1  # At most one iteration per block + 1
        iterations = 0

        while len(ordered) < len(blocks):
            iterations += 1
            if iterations > max_iterations:
                # Circular reference or corrupt data detected
                for block in blocks:
                    if block["id"] not in added:
                        ordered.append(block)
                        added.add(block["id"])
                break

            added_this_round = False
            for block in blocks:
                if block["id"] not in added and can_add(block):
                    ordered.append(block)
                    added.add(block["id"])
                    added_this_round = True

            if not added_this_round:
                # Remaining blocks don't connect to current chain
                # Add them anyway (may indicate diverged history)
                for block in blocks:
                    if block["id"] not in added:
                        ordered.append(block)
                        added.add(block["id"])
                break

        return ordered

    def _register_imported_learnings(self, ledger: Ledger, block_data: dict) -> None:
        """Register learnings from an imported block in reinforcements.json.

        Args:
            ledger: Target ledger
            block_data: The imported block data
        """
        from .ledger.models import Learning, compute_content_hash

        learnings_data = block_data.get("learnings", [])
        if not learnings_data:
            return

        block_id = block_data.get("id")

        with file_lock(ledger.reinforcements_file, exclusive=True):
            if ledger.reinforcements_file.exists():
                with open(ledger.reinforcements_file) as f:
                    reinforcements = json.load(f)
            else:
                reinforcements = {"learnings": {}}

            for learning_data in learnings_data:
                learning_id = learning_data.get("id")
                if not learning_id:
                    continue

                # Skip if already registered
                if learning_id in reinforcements.get("learnings", {}):
                    continue

                content = learning_data.get("content", "")
                content_hash = learning_data.get("content_hash") or compute_content_hash(content)

                reinforcements["learnings"][learning_id] = {
                    "category": learning_data.get("category", "discovery"),
                    "content": content,
                    "confidence": learning_data.get("confidence", 0.5),
                    "outcome_count": 0,
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                    "last_applied": datetime.now(timezone.utc).isoformat(),
                    "block_id": block_id,
                    "content_hash": content_hash,
                    "outcomes": [],
                    "imported_at": datetime.now(timezone.utc).isoformat(),
                }

            with open(ledger.reinforcements_file, "w") as f:
                json.dump(reinforcements, f, indent=2, default=str)

    def pull(self, verify: bool = True) -> SyncResult:
        """Pull blocks from remote that we don't have locally.

        Args:
            verify: If True, verify block hashes before importing

        Returns:
            SyncResult with details of the operation
        """
        info = self.get_sync_info()
        result = SyncResult(status=info.status)

        if not info.missing_locally:
            return result

        # Get remote blocks in chain order
        remote_chain = self._get_block_chain(self.remote_ledger)
        blocks_to_import = []

        for block_id in remote_chain:
            if block_id in info.missing_locally:
                block = self.remote_ledger.get_block(block_id)
                if block:
                    block_data = block.model_dump(mode="json")

                    # Verify hash if requested
                    if verify and not self._verify_block(block_data):
                        result.errors.append(
                            f"Block {block_id} failed hash verification (possible tampering)"
                        )
                        continue

                    blocks_to_import.append(block_data)

        # Import blocks
        for block_data in blocks_to_import:
            block_id = block_data.get("id")
            if self._import_block(block_data, self.local_ledger):
                result.blocks_imported.append(block_id)
                # Register learnings from imported block
                self._register_imported_learnings(self.local_ledger, block_data)
            else:
                result.errors.append(f"Failed to import block {block_id}")

        # Update index
        if result.blocks_imported:
            imported_blocks = [
                b for b in blocks_to_import
                if b.get("id") in result.blocks_imported
            ]
            if not self._update_index(self.local_ledger, imported_blocks):
                result.errors.append("Failed to update local index")

        # Update status
        if result.errors:
            result.status = info.status
        elif result.blocks_imported:
            new_info = self.get_sync_info()
            result.status = new_info.status

        return result

    def push(self, verify: bool = True) -> SyncResult:
        """Push local blocks that remote doesn't have.

        Args:
            verify: If True, verify block hashes before exporting

        Returns:
            SyncResult with details of the operation
        """
        info = self.get_sync_info()
        result = SyncResult(status=info.status)
        result.blocks_to_export = list(info.missing_remotely)

        if not info.missing_remotely:
            return result

        # Get local blocks in chain order
        local_chain = self._get_block_chain(self.local_ledger)
        blocks_to_export = []

        for block_id in local_chain:
            if block_id in info.missing_remotely:
                block = self.local_ledger.get_block(block_id)
                if block:
                    block_data = block.model_dump(mode="json")

                    # Verify hash if requested
                    if verify and not self._verify_block(block_data):
                        result.errors.append(
                            f"Block {block_id} failed hash verification"
                        )
                        continue

                    blocks_to_export.append(block_data)

        # Export blocks to remote
        exported_ids = []
        for block_data in blocks_to_export:
            block_id = block_data.get("id")
            if self._import_block(block_data, self.remote_ledger):
                exported_ids.append(block_id)
                # Register learnings in remote ledger
                self._register_imported_learnings(self.remote_ledger, block_data)
            else:
                result.errors.append(f"Failed to export block {block_id}")

        # Update remote index
        if exported_ids:
            exported_blocks = [
                b for b in blocks_to_export
                if b.get("id") in exported_ids
            ]
            if not self._update_index(self.remote_ledger, exported_blocks):
                result.errors.append("Failed to update remote index")

        # Update status
        if result.errors:
            result.status = info.status
        else:
            new_info = self.get_sync_info()
            result.status = new_info.status

        return result

    def sync(self, verify: bool = True) -> SyncResult:
        """Bidirectional sync - pull then push.

        Args:
            verify: If True, verify block hashes during sync

        Returns:
            Combined SyncResult from both operations
        """
        # Pull first
        pull_result = self.pull(verify=verify)

        # Then push
        push_result = self.push(verify=verify)

        # Combine results
        final_info = self.get_sync_info()

        return SyncResult(
            status=final_info.status,
            blocks_imported=pull_result.blocks_imported,
            blocks_to_export=push_result.blocks_to_export,
            errors=pull_result.errors + push_result.errors,
        )


def export_ledger(ledger_path: Path, output_path: Path) -> None:
    """Export ledger to a tar.gz archive for transfer.

    The archive includes:
    - blocks/*.json (immutable block files)
    - index.json (chain index)
    - reinforcements.json (mutable confidence/outcome data)

    Args:
        ledger_path: Path to ledger directory
        output_path: Path for output .tar.gz file

    Raises:
        NotADirectoryError: If ledger_path doesn't exist
        FileExistsError: If output_path already exists
    """
    ledger_path = Path(ledger_path)
    output_path = Path(output_path)

    if not ledger_path.exists():
        raise NotADirectoryError(f"Ledger path does not exist: {ledger_path}")

    if output_path.exists():
        raise FileExistsError(f"Output file already exists: {output_path}")

    # Ensure output has .tar.gz extension
    if not str(output_path).endswith('.tar.gz'):
        output_path = Path(str(output_path) + '.tar.gz')

    with tarfile.open(output_path, "w:gz") as tar:
        # Add blocks directory
        blocks_dir = ledger_path / "blocks"
        if blocks_dir.exists():
            for block_file in blocks_dir.glob("*.json"):
                tar.add(block_file, arcname=f"blocks/{block_file.name}")

        # Add index.json
        index_file = ledger_path / "index.json"
        if index_file.exists():
            tar.add(index_file, arcname="index.json")

        # Add reinforcements.json
        reinforcements_file = ledger_path / "reinforcements.json"
        if reinforcements_file.exists():
            tar.add(reinforcements_file, arcname="reinforcements.json")

        # Add imports.json if exists (for project ledgers)
        imports_file = ledger_path / "imports.json"
        if imports_file.exists():
            tar.add(imports_file, arcname="imports.json")


def import_ledger(archive_path: Path, ledger_path: Path) -> SyncResult:
    """Import ledger from a tar.gz archive.

    This performs a merge operation - existing blocks are preserved,
    new blocks from the archive are added.

    Args:
        archive_path: Path to .tar.gz archive
        ledger_path: Path to target ledger directory

    Returns:
        SyncResult with details of imported blocks

    Raises:
        FileNotFoundError: If archive doesn't exist
    """
    archive_path = Path(archive_path)
    ledger_path = Path(ledger_path)

    if not archive_path.exists():
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    result = SyncResult(status=SyncStatus.IN_SYNC)

    # Create temp directory for extraction
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Extract archive (filter="data" for security - Python 3.12+)
        with tarfile.open(archive_path, "r:gz") as tar:
            if sys.version_info >= (3, 12):
                tar.extractall(temp_path, filter="data")
            else:
                # Manual path traversal protection for Python < 3.12
                for member in tar.getmembers():
                    member_path = Path(temp_path) / member.name
                    try:
                        member_path.resolve().relative_to(Path(temp_path).resolve())
                    except ValueError:
                        raise ValueError(f"Archive member '{member.name}' attempts path traversal - rejected for security")
                tar.extractall(temp_path)

        # Ensure target ledger exists
        ledger_path.mkdir(parents=True, exist_ok=True)
        (ledger_path / "blocks").mkdir(exist_ok=True)

        # Initialize target ledger if needed
        target_ledger = Ledger(ledger_path)

        # Get existing block IDs
        existing_ids = set()
        if target_ledger.index_file.exists():
            index = target_ledger._read_json(target_ledger.index_file)
            existing_ids = {b["id"] for b in index.get("blocks", [])}

        # Import blocks from archive
        archive_blocks_dir = temp_path / "blocks"
        new_blocks = []

        if archive_blocks_dir.exists():
            for block_file in archive_blocks_dir.glob("*.json"):
                try:
                    with open(block_file) as f:
                        block_data = json.load(f)

                    block_id = block_data.get("id")
                    if not block_id:
                        continue

                    if block_id in existing_ids:
                        continue

                    # Verify block hash
                    block = Block.model_validate(block_data)
                    stored_hash = block_data.get("hash")
                    if stored_hash and block.hash != stored_hash:
                        result.errors.append(
                            f"Block {block_id} failed hash verification"
                        )
                        continue

                    # Copy block file
                    target_block_file = ledger_path / "blocks" / block_file.name
                    shutil.copy2(block_file, target_block_file)

                    new_blocks.append(block_data)
                    result.blocks_imported.append(block_id)

                except Exception as e:
                    result.errors.append(f"Failed to import {block_file.name}: {e}")

        # Merge reinforcements
        archive_reinforcements = temp_path / "reinforcements.json"
        if archive_reinforcements.exists():
            try:
                with open(archive_reinforcements) as f:
                    archive_data = json.load(f)

                with file_lock(target_ledger.reinforcements_file, exclusive=True):
                    if target_ledger.reinforcements_file.exists():
                        with open(target_ledger.reinforcements_file) as f:
                            target_data = json.load(f)
                    else:
                        target_data = {"learnings": {}}

                    # Merge learnings (archive data takes precedence for new entries)
                    for learning_id, data in archive_data.get("learnings", {}).items():
                        if learning_id not in target_data["learnings"]:
                            target_data["learnings"][learning_id] = data

                    with open(target_ledger.reinforcements_file, "w") as f:
                        json.dump(target_data, f, indent=2, default=str)

            except Exception as e:
                result.errors.append(f"Failed to merge reinforcements: {e}")

        # Update index with new blocks
        if new_blocks:
            # Read archive index for ordering
            archive_index = temp_path / "index.json"
            block_order = []

            if archive_index.exists():
                try:
                    with open(archive_index) as f:
                        idx_data = json.load(f)
                    block_order = [b["id"] for b in idx_data.get("blocks", [])]
                except Exception:
                    pass

            # Order new blocks according to archive index
            ordered_blocks = []
            new_ids = {b["id"] for b in new_blocks}

            for block_id in block_order:
                if block_id in new_ids:
                    for b in new_blocks:
                        if b["id"] == block_id:
                            ordered_blocks.append(b)
                            break

            # Add any blocks not in index
            for b in new_blocks:
                if b["id"] not in [ob["id"] for ob in ordered_blocks]:
                    ordered_blocks.append(b)

            # Update target index
            with file_lock(target_ledger.index_file, exclusive=True):
                with open(target_ledger.index_file) as f:
                    index = json.load(f)

                for block_data in ordered_blocks:
                    block_id = block_data.get("id")
                    index["blocks"].append({
                        "id": block_id,
                        "timestamp": block_data.get("timestamp"),
                        "hash": block_data.get("hash"),
                        "parent": block_data.get("parent_block"),
                    })
                    index["head"] = block_id

                with open(target_ledger.index_file, "w") as f:
                    json.dump(index, f, indent=2, default=str)

    # Determine final status
    if result.errors:
        result.status = SyncStatus.DIVERGED
    elif result.blocks_imported:
        result.status = SyncStatus.IN_SYNC

    return result
