"""Tests for the ledger sync functionality."""

import json
import tarfile
import pytest
from pathlib import Path

from claude_cortex.ledger import Ledger, Learning, LearningCategory
from claude_cortex.sync import (
    LedgerSync,
    SyncStatus,
    SyncResult,
    SyncInfo,
    export_ledger,
    import_ledger,
)


@pytest.fixture
def local_ledger(temp_dir):
    """Create a local ledger for testing."""
    path = temp_dir / "local_ledger"
    path.mkdir(parents=True)
    return Ledger(path)


@pytest.fixture
def remote_ledger(temp_dir):
    """Create a remote ledger for testing."""
    path = temp_dir / "remote_ledger"
    path.mkdir(parents=True)
    return Ledger(path)


@pytest.fixture
def local_ledger_with_blocks(local_ledger):
    """Create a local ledger with some test blocks."""
    learning1 = Learning(
        category=LearningCategory.DISCOVERY,
        content="Local discovery one",
        confidence=0.8,
    )
    learning2 = Learning(
        category=LearningCategory.PATTERN,
        content="Local pattern two",
        confidence=0.7,
    )

    local_ledger.append_block(
        session_id="local-session-1",
        learnings=[learning1],
        deduplicate=False,
    )
    local_ledger.append_block(
        session_id="local-session-2",
        learnings=[learning2],
        deduplicate=False,
    )

    return local_ledger


@pytest.fixture
def remote_ledger_with_blocks(remote_ledger):
    """Create a remote ledger with some test blocks."""
    learning1 = Learning(
        category=LearningCategory.DISCOVERY,
        content="Remote discovery one",
        confidence=0.8,
    )
    learning2 = Learning(
        category=LearningCategory.ERROR,
        content="Remote error two",
        confidence=0.6,
    )

    remote_ledger.append_block(
        session_id="remote-session-1",
        learnings=[learning1],
        deduplicate=False,
    )
    remote_ledger.append_block(
        session_id="remote-session-2",
        learnings=[learning2],
        deduplicate=False,
    )

    return remote_ledger


class TestSyncInfoIdentical:
    """Tests for sync_info when ledgers are identical."""

    def test_sync_info_identical_ledgers(self, temp_dir):
        """Returns IN_SYNC status for identical ledgers."""
        # Create two identical ledgers
        local_path = temp_dir / "local"
        remote_path = temp_dir / "remote"
        local_path.mkdir()
        remote_path.mkdir()

        local_ledger = Ledger(local_path)
        remote_ledger = Ledger(remote_path)

        # Add identical content to both
        learning = Learning(
            category=LearningCategory.DISCOVERY,
            content="Shared discovery",
            confidence=0.8,
        )

        local_ledger.append_block(
            session_id="shared-session",
            learnings=[learning],
            deduplicate=False,
        )
        remote_ledger.append_block(
            session_id="shared-session",
            learnings=[learning],
            deduplicate=False,
        )

        # Note: Due to timestamps, the blocks will have different IDs
        # So for truly identical ledgers, we need to copy files
        import shutil
        shutil.rmtree(remote_path)
        shutil.copytree(local_path, remote_path)

        sync = LedgerSync(local_path, remote_path)
        info = sync.get_sync_info()

        assert info.status == SyncStatus.IN_SYNC
        assert len(info.missing_locally) == 0
        assert len(info.missing_remotely) == 0

    def test_sync_info_empty_ledgers(self, local_ledger, remote_ledger):
        """Empty ledgers should be IN_SYNC."""
        sync = LedgerSync(local_ledger.path, remote_ledger.path)
        info = sync.get_sync_info()

        assert info.status == SyncStatus.IN_SYNC
        assert info.local_block_count == 0
        assert info.remote_block_count == 0


class TestSyncInfoLocalAhead:
    """Tests for sync_info when local has more blocks."""

    def test_sync_info_local_ahead(self, local_ledger_with_blocks, remote_ledger):
        """Detects when local has more blocks."""
        sync = LedgerSync(local_ledger_with_blocks.path, remote_ledger.path)
        info = sync.get_sync_info()

        assert info.status == SyncStatus.LOCAL_AHEAD
        assert info.local_block_count == 2
        assert info.remote_block_count == 0
        assert len(info.missing_remotely) == 2
        assert len(info.missing_locally) == 0


class TestSyncInfoRemoteAhead:
    """Tests for sync_info when remote has more blocks."""

    def test_sync_info_remote_ahead(self, local_ledger, remote_ledger_with_blocks):
        """Detects when remote has more blocks."""
        sync = LedgerSync(local_ledger.path, remote_ledger_with_blocks.path)
        info = sync.get_sync_info()

        assert info.status == SyncStatus.REMOTE_AHEAD
        assert info.local_block_count == 0
        assert info.remote_block_count == 2
        assert len(info.missing_locally) == 2
        assert len(info.missing_remotely) == 0


class TestSyncPull:
    """Tests for pulling blocks from remote."""

    def test_pull_imports_missing_blocks(self, local_ledger, remote_ledger_with_blocks):
        """Pull should bring in missing blocks from remote."""
        sync = LedgerSync(local_ledger.path, remote_ledger_with_blocks.path)

        # Verify local is empty
        assert local_ledger.get_head() is None

        # Pull from remote
        result = sync.pull()

        assert len(result.blocks_imported) == 2
        assert len(result.errors) == 0

        # Verify blocks are now in local
        # Reload ledger to see changes
        local_reloaded = Ledger(local_ledger.path)
        assert local_reloaded.get_head() is not None

    def test_pull_with_verify_flag(self, local_ledger, remote_ledger_with_blocks, temp_dir):
        """Pull with verify=True should process blocks normally when valid.

        Note: The pull() method calls get_block() which parses the JSON through
        Pydantic, recomputing the hash. The _verify_block method then compares
        the recomputed hash against the value in the serialized block_data,
        which are the same unless there's a parsing/serialization issue.

        True hash verification (detecting content tampering) is best done via
        import_ledger() which reads the raw JSON and compares stored vs computed hashes.
        """
        sync = LedgerSync(local_ledger.path, remote_ledger_with_blocks.path)

        # Pull with verification enabled
        result = sync.pull(verify=True)

        # Valid blocks should import successfully
        assert len(result.blocks_imported) == 2
        assert len(result.errors) == 0

    def test_pull_without_verify_flag(self, local_ledger, remote_ledger_with_blocks, temp_dir):
        """Pull with verify=False should skip hash verification."""
        sync = LedgerSync(local_ledger.path, remote_ledger_with_blocks.path)

        # Pull without verification
        result = sync.pull(verify=False)

        # Blocks should import
        assert len(result.blocks_imported) == 2
        assert len(result.errors) == 0

    def test_pull_no_changes_when_in_sync(self, temp_dir):
        """Pull should do nothing when already in sync."""
        local_path = temp_dir / "local"
        remote_path = temp_dir / "remote"
        local_path.mkdir()

        local_ledger = Ledger(local_path)
        learning = Learning(
            category=LearningCategory.DISCOVERY,
            content="Shared content",
            confidence=0.8,
        )
        local_ledger.append_block(
            session_id="session-1",
            learnings=[learning],
            deduplicate=False,
        )

        # Copy to remote
        import shutil
        shutil.copytree(local_path, remote_path)

        sync = LedgerSync(local_path, remote_path)
        result = sync.pull()

        assert len(result.blocks_imported) == 0
        assert len(result.errors) == 0


class TestSyncPush:
    """Tests for pushing blocks to remote."""

    def test_push_exports_blocks(self, local_ledger_with_blocks, remote_ledger):
        """Push should send local blocks to remote."""
        sync = LedgerSync(local_ledger_with_blocks.path, remote_ledger.path)

        # Verify remote is empty
        assert remote_ledger.get_head() is None

        # Push to remote
        result = sync.push()

        assert len(result.blocks_to_export) == 2
        assert len(result.errors) == 0

        # Verify blocks are now in remote
        remote_reloaded = Ledger(remote_ledger.path)
        assert remote_reloaded.get_head() is not None

    def test_push_no_changes_when_remote_has_all(self, temp_dir):
        """Push should do nothing when remote has all blocks."""
        local_path = temp_dir / "local"
        remote_path = temp_dir / "remote"
        local_path.mkdir()

        local_ledger = Ledger(local_path)
        learning = Learning(
            category=LearningCategory.DISCOVERY,
            content="Shared content",
            confidence=0.8,
        )
        local_ledger.append_block(
            session_id="session-1",
            learnings=[learning],
            deduplicate=False,
        )

        # Copy to remote
        import shutil
        shutil.copytree(local_path, remote_path)

        sync = LedgerSync(local_path, remote_path)
        result = sync.push()

        assert len(result.blocks_to_export) == 0
        assert len(result.errors) == 0


class TestSyncBidirectional:
    """Tests for bidirectional sync."""

    def test_sync_bidirectional(self, temp_dir):
        """Full sync should work both directions."""
        local_path = temp_dir / "local"
        remote_path = temp_dir / "remote"
        local_path.mkdir()
        remote_path.mkdir()

        local_ledger = Ledger(local_path)
        remote_ledger = Ledger(remote_path)

        # Add different content to each
        local_learning = Learning(
            category=LearningCategory.DISCOVERY,
            content="Local only content",
            confidence=0.8,
        )
        remote_learning = Learning(
            category=LearningCategory.PATTERN,
            content="Remote only content",
            confidence=0.7,
        )

        local_ledger.append_block(
            session_id="local-session",
            learnings=[local_learning],
            deduplicate=False,
        )
        remote_ledger.append_block(
            session_id="remote-session",
            learnings=[remote_learning],
            deduplicate=False,
        )

        sync = LedgerSync(local_path, remote_path)
        result = sync.sync()

        # Both should have blocks imported/exported
        assert len(result.blocks_imported) == 1  # From remote
        assert len(result.blocks_to_export) == 1  # To remote
        assert len(result.errors) == 0

        # Verify both ledgers now have both blocks
        local_reloaded = Ledger(local_path)
        remote_reloaded = Ledger(remote_path)

        local_blocks = local_reloaded.get_all_blocks()
        remote_blocks = remote_reloaded.get_all_blocks()

        assert len(local_blocks) == 2
        assert len(remote_blocks) == 2


class TestExportLedger:
    """Tests for ledger export functionality."""

    def test_export_creates_archive(self, local_ledger_with_blocks, temp_dir):
        """Export should create a valid tar.gz archive."""
        output_path = temp_dir / "export.tar.gz"

        export_ledger(local_ledger_with_blocks.path, output_path)

        assert output_path.exists()

        # Verify it's a valid tar.gz
        with tarfile.open(output_path, "r:gz") as tar:
            names = tar.getnames()
            assert "index.json" in names
            # Should have block files
            assert any(name.startswith("blocks/") for name in names)

    def test_export_includes_reinforcements(self, local_ledger_with_blocks, temp_dir):
        """Export should include reinforcements.json if it exists."""
        # Ensure reinforcements.json exists
        reinforcements_file = local_ledger_with_blocks.path / "reinforcements.json"
        assert reinforcements_file.exists()

        output_path = temp_dir / "export.tar.gz"
        export_ledger(local_ledger_with_blocks.path, output_path)

        with tarfile.open(output_path, "r:gz") as tar:
            names = tar.getnames()
            assert "reinforcements.json" in names

    def test_export_adds_extension(self, local_ledger_with_blocks, temp_dir):
        """Export should add .tar.gz extension if missing."""
        output_path = temp_dir / "export"

        export_ledger(local_ledger_with_blocks.path, output_path)

        # Should have added .tar.gz extension
        expected_path = temp_dir / "export.tar.gz"
        assert expected_path.exists()

    def test_export_fails_if_exists(self, local_ledger_with_blocks, temp_dir):
        """Export should fail if output file already exists."""
        output_path = temp_dir / "export.tar.gz"
        output_path.touch()

        with pytest.raises(FileExistsError):
            export_ledger(local_ledger_with_blocks.path, output_path)

    def test_export_fails_nonexistent_ledger(self, temp_dir):
        """Export should fail if ledger doesn't exist."""
        nonexistent = temp_dir / "nonexistent"
        output_path = temp_dir / "export.tar.gz"

        with pytest.raises(NotADirectoryError):
            export_ledger(nonexistent, output_path)


class TestImportLedger:
    """Tests for ledger import functionality."""

    def test_import_from_archive(self, local_ledger_with_blocks, temp_dir):
        """Import should restore from archive."""
        # Export first
        archive_path = temp_dir / "export.tar.gz"
        export_ledger(local_ledger_with_blocks.path, archive_path)

        # Import to new location
        import_path = temp_dir / "imported"
        import_path.mkdir()

        result = import_ledger(archive_path, import_path)

        assert len(result.blocks_imported) == 2
        assert len(result.errors) == 0
        assert result.status == SyncStatus.IN_SYNC

        # Verify imported ledger
        imported_ledger = Ledger(import_path)
        assert imported_ledger.get_head() is not None

    def test_import_merges_with_existing(self, local_ledger_with_blocks, remote_ledger_with_blocks, temp_dir):
        """Import should merge with existing ledger."""
        # Export remote
        archive_path = temp_dir / "remote_export.tar.gz"
        export_ledger(remote_ledger_with_blocks.path, archive_path)

        # Import to local (which already has blocks)
        result = import_ledger(archive_path, local_ledger_with_blocks.path)

        assert len(result.blocks_imported) == 2  # Remote had 2 blocks
        assert len(result.errors) == 0

        # Verify local now has all blocks
        local_reloaded = Ledger(local_ledger_with_blocks.path)
        blocks = local_reloaded.get_all_blocks()
        assert len(blocks) == 4  # 2 original + 2 imported

    def test_import_verifies_hashes(self, temp_dir):
        """Import should reject blocks with invalid hashes."""
        # Create a ledger and export it
        ledger_path = temp_dir / "ledger"
        ledger_path.mkdir()
        ledger = Ledger(ledger_path)

        learning = Learning(
            category=LearningCategory.DISCOVERY,
            content="Test content",
            confidence=0.8,
        )
        ledger.append_block(
            session_id="session-1",
            learnings=[learning],
            deduplicate=False,
        )

        archive_path = temp_dir / "export.tar.gz"
        export_ledger(ledger_path, archive_path)

        # Tamper with the archive
        tampered_dir = temp_dir / "tampered"
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(tampered_dir, filter="data")

        # Modify a block file
        block_files = list((tampered_dir / "blocks").glob("*.json"))
        if block_files:
            block_file = block_files[0]
            with open(block_file) as f:
                block_data = json.load(f)
            block_data["session_id"] = "tampered"
            with open(block_file, "w") as f:
                json.dump(block_data, f)

        # Recreate tampered archive
        tampered_archive = temp_dir / "tampered.tar.gz"
        with tarfile.open(tampered_archive, "w:gz") as tar:
            for item in tampered_dir.iterdir():
                if item.is_dir():
                    for subitem in item.iterdir():
                        tar.add(subitem, arcname=f"{item.name}/{subitem.name}")
                else:
                    tar.add(item, arcname=item.name)

        # Import tampered archive
        import_path = temp_dir / "imported"
        import_path.mkdir()

        result = import_ledger(tampered_archive, import_path)

        # Should have hash verification error
        assert any("hash verification" in err for err in result.errors)

    def test_import_nonexistent_archive(self, temp_dir):
        """Import should fail if archive doesn't exist."""
        nonexistent = temp_dir / "nonexistent.tar.gz"
        import_path = temp_dir / "imported"

        with pytest.raises(FileNotFoundError):
            import_ledger(nonexistent, import_path)

    def test_import_creates_target_directory(self, local_ledger_with_blocks, temp_dir):
        """Import should create target directory if it doesn't exist."""
        archive_path = temp_dir / "export.tar.gz"
        export_ledger(local_ledger_with_blocks.path, archive_path)

        import_path = temp_dir / "new" / "nested" / "path"

        result = import_ledger(archive_path, import_path)

        assert import_path.exists()
        assert len(result.blocks_imported) == 2


class TestLedgerSyncValidation:
    """Tests for LedgerSync path validation."""

    def test_ssh_path_rejected(self, local_ledger, temp_dir):
        """SSH paths should be rejected with a clear error."""
        with pytest.raises(ValueError, match="SSH paths not yet supported"):
            LedgerSync(local_ledger.path, "user@host:/path/to/ledger")

    def test_nonexistent_local_path(self, temp_dir, remote_ledger):
        """Nonexistent local path should raise error."""
        nonexistent = temp_dir / "nonexistent"

        with pytest.raises(NotADirectoryError, match="Local ledger path"):
            LedgerSync(nonexistent, remote_ledger.path)

    def test_nonexistent_remote_path(self, local_ledger, temp_dir):
        """Nonexistent remote path should raise error."""
        nonexistent = temp_dir / "nonexistent"

        with pytest.raises(NotADirectoryError, match="Remote ledger path"):
            LedgerSync(local_ledger.path, nonexistent)


class TestSyncStatus:
    """Tests for SyncStatus enum."""

    def test_sync_status_values(self):
        """SyncStatus should have expected values."""
        assert SyncStatus.IN_SYNC.value == "in_sync"
        assert SyncStatus.LOCAL_AHEAD.value == "local_ahead"
        assert SyncStatus.REMOTE_AHEAD.value == "remote_ahead"
        assert SyncStatus.DIVERGED.value == "diverged"


class TestSyncInfoDataclass:
    """Tests for SyncInfo dataclass."""

    def test_sync_info_defaults(self):
        """SyncInfo should have correct defaults."""
        info = SyncInfo(
            local_root=None,
            remote_root=None,
            local_block_count=0,
            remote_block_count=0,
            status=SyncStatus.IN_SYNC,
        )

        assert info.missing_locally == []
        assert info.missing_remotely == []


class TestSyncResultDataclass:
    """Tests for SyncResult dataclass."""

    def test_sync_result_defaults(self):
        """SyncResult should have correct defaults."""
        result = SyncResult(status=SyncStatus.IN_SYNC)

        assert result.blocks_imported == []
        assert result.blocks_to_export == []
        assert result.errors == []
