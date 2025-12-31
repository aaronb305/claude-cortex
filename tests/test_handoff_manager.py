"""Tests for the HandoffManager class."""

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from claude_cortex.handoff.manager import HandoffManager
from claude_cortex.handoff.models import Handoff


class TestHandoffCreation:
    """Tests for HandoffManager.create_handoff method."""

    def test_create_handoff_creates_proper_structure(self, project_dir):
        """Should create a Handoff with all required fields."""
        manager = HandoffManager(project_dir)

        handoff = manager.create_handoff(
            session_id="test-session-123",
            completed_tasks=["Task A", "Task B"],
            pending_tasks=["Task C"],
            blockers=["Blocker 1"],
            context_notes="Some context notes",
        )

        assert isinstance(handoff, Handoff)
        assert handoff.session_id == "test-session-123"
        assert handoff.completed_tasks == ["Task A", "Task B"]
        assert handoff.pending_tasks == ["Task C"]
        assert handoff.blockers == ["Blocker 1"]
        assert handoff.context_notes == "Some context notes"

    def test_create_handoff_includes_timestamp(self, project_dir):
        """Should include a timestamp when creating a handoff."""
        manager = HandoffManager(project_dir)

        before = datetime.now(timezone.utc)
        handoff = manager.create_handoff(
            session_id="test-session",
            completed_tasks=["Done"],
        )
        after = datetime.now(timezone.utc)

        assert handoff.timestamp is not None
        assert before <= handoff.timestamp <= after

    def test_create_handoff_with_empty_tasks(self, project_dir):
        """Should handle empty task lists correctly."""
        manager = HandoffManager(project_dir)

        handoff = manager.create_handoff(
            session_id="test-session",
        )

        assert handoff.completed_tasks == []
        assert handoff.pending_tasks == []
        assert handoff.blockers == []
        assert handoff.context_notes == ""

    def test_create_handoff_defaults_to_empty_context_notes(self, project_dir):
        """Should default context_notes to empty string."""
        manager = HandoffManager(project_dir)

        handoff = manager.create_handoff(
            session_id="test-session",
            completed_tasks=["Task 1"],
        )

        assert handoff.context_notes == ""

    @patch("claude_cortex.handoff.manager.HandoffManager._get_modified_files")
    def test_create_handoff_captures_modified_files(self, mock_get_modified, project_dir):
        """Should capture modified files from git."""
        mock_get_modified.return_value = ["file1.py", "file2.py"]
        manager = HandoffManager(project_dir)

        handoff = manager.create_handoff(
            session_id="test-session",
            completed_tasks=["Fixed bugs"],
        )

        assert handoff.modified_files == ["file1.py", "file2.py"]


class TestHandoffSaving:
    """Tests for HandoffManager.save_handoff method."""

    def test_save_handoff_writes_to_correct_path(self, project_dir):
        """Should write handoff to the correct directory structure."""
        manager = HandoffManager(project_dir)

        handoff = Handoff(
            session_id="session-abc",
            timestamp=datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc),
            completed_tasks=["Task 1"],
            pending_tasks=["Task 2"],
        )

        saved_path = manager.save_handoff(handoff)

        assert saved_path.exists()
        assert saved_path.parent.name == "session-abc"
        assert saved_path.parent.parent.name == "handoffs"
        assert saved_path.name == "handoff-20240115-103045-000000.md"

    def test_save_handoff_creates_directories_if_needed(self, project_dir):
        """Should create .claude/handoffs/<session_id> directories."""
        manager = HandoffManager(project_dir)

        # Ensure directories don't exist yet
        handoffs_dir = project_dir / ".claude" / "handoffs"
        assert not handoffs_dir.exists()

        handoff = Handoff(
            session_id="new-session",
            timestamp=datetime(2024, 2, 20, 14, 0, 0, tzinfo=timezone.utc),
            completed_tasks=["Created new feature"],
        )

        saved_path = manager.save_handoff(handoff)

        assert saved_path.exists()
        assert (project_dir / ".claude" / "handoffs" / "new-session").is_dir()

    def test_save_handoff_proper_file_naming_with_timestamp(self, project_dir):
        """Should name files with timestamp in correct format."""
        manager = HandoffManager(project_dir)

        handoff = Handoff(
            session_id="test-session",
            timestamp=datetime(2024, 3, 5, 8, 15, 30, tzinfo=timezone.utc),
            completed_tasks=["Work done"],
        )

        saved_path = manager.save_handoff(handoff)

        assert saved_path.name == "handoff-20240305-081530-000000.md"

    def test_save_handoff_writes_valid_markdown(self, project_dir):
        """Should write valid markdown content to the file."""
        manager = HandoffManager(project_dir)

        handoff = Handoff(
            session_id="test-session",
            timestamp=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            completed_tasks=["Implemented feature X"],
            pending_tasks=["Add tests"],
            context_notes="Important context",
        )

        saved_path = manager.save_handoff(handoff)

        content = saved_path.read_text(encoding="utf-8")
        assert "session_id: test-session" in content
        assert "Implemented feature X" in content
        assert "Add tests" in content
        assert "Important context" in content


class TestHandoffLoading:
    """Tests for HandoffManager.load_latest_handoff method."""

    def test_load_latest_handoff_finds_most_recent(self, project_dir):
        """Should return the most recent handoff file."""
        manager = HandoffManager(project_dir)

        # Create multiple handoffs with different timestamps
        handoff_old = Handoff(
            session_id="test-session",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            completed_tasks=["Old task"],
        )
        handoff_new = Handoff(
            session_id="test-session",
            timestamp=datetime(2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc),
            completed_tasks=["New task"],
        )

        manager.save_handoff(handoff_old)
        manager.save_handoff(handoff_new)

        loaded = manager.load_latest_handoff(session_id="test-session")

        assert loaded is not None
        assert loaded.completed_tasks == ["New task"]

    def test_load_latest_handoff_returns_none_when_no_handoffs(self, project_dir):
        """Should return None when no handoffs exist."""
        manager = HandoffManager(project_dir)

        loaded = manager.load_latest_handoff()

        assert loaded is None

    def test_load_latest_handoff_returns_none_for_nonexistent_session(self, project_dir):
        """Should return None for a non-existent session ID."""
        manager = HandoffManager(project_dir)

        # Create a handoff in one session
        handoff = Handoff(
            session_id="existing-session",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            completed_tasks=["Task"],
        )
        manager.save_handoff(handoff)

        # Try to load from a different session
        loaded = manager.load_latest_handoff(session_id="nonexistent-session")

        assert loaded is None

    def test_load_latest_handoff_handles_malformed_files_gracefully(self, project_dir):
        """Should skip malformed files and try to find a valid one."""
        manager = HandoffManager(project_dir)

        # Create a valid handoff first
        handoff = Handoff(
            session_id="test-session",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            completed_tasks=["Valid task"],
        )
        valid_path = manager.save_handoff(handoff)

        # Create a malformed handoff file (newer timestamp so it's tried first)
        session_dir = project_dir / ".claude" / "handoffs" / "test-session"
        malformed_path = session_dir / "handoff-20240102-120000.md"
        malformed_path.write_text("This is not a valid handoff format", encoding="utf-8")

        loaded = manager.load_latest_handoff(session_id="test-session")

        # Should load the valid older handoff
        assert loaded is not None
        assert loaded.completed_tasks == ["Valid task"]

    def test_load_latest_handoff_across_all_sessions(self, project_dir):
        """Should find latest handoff across all sessions when no session_id specified."""
        manager = HandoffManager(project_dir)

        handoff1 = Handoff(
            session_id="session-1",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            completed_tasks=["Session 1 task"],
        )
        handoff2 = Handoff(
            session_id="session-2",
            timestamp=datetime(2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc),
            completed_tasks=["Session 2 task"],
        )

        manager.save_handoff(handoff1)
        manager.save_handoff(handoff2)

        loaded = manager.load_latest_handoff()

        assert loaded is not None
        assert loaded.completed_tasks == ["Session 2 task"]


class TestGitIntegration:
    """Tests for git-related functionality."""

    def test_get_modified_files_returns_changed_files(self, project_dir):
        """Should return list of modified files from git status."""
        manager = HandoffManager(project_dir)

        mock_result = MagicMock()
        mock_result.returncode = 0
        # Git porcelain format: XY filename (XY = 2-char status, then space, then filename)
        # "A " = staged added, "M " = staged modified, "??" = untracked
        # Note: Lines starting with space (e.g., " M") would have leading space stripped
        # if they're at the start of stdout, so we start with a non-space status
        mock_result.stdout = "".join([
            "M  file1.py\n",
            "A  file2.py\n",
            "?? untracked.txt\n",
        ])

        with patch("claude_cortex.handoff.manager.subprocess.run", return_value=mock_result) as mock_run:
            files = manager._get_modified_files()

        assert "file1.py" in files
        assert "file2.py" in files
        assert "untracked.txt" in files
        mock_run.assert_called_once()

    def test_get_modified_files_handles_non_git_directories(self, project_dir):
        """Should return empty list for non-git directories."""
        manager = HandoffManager(project_dir)

        mock_result = MagicMock()
        mock_result.returncode = 128  # git error code for not a repository

        with patch("claude_cortex.handoff.manager.subprocess.run", return_value=mock_result):
            files = manager._get_modified_files()

        assert files == []

    def test_get_modified_files_handles_renamed_files(self, project_dir):
        """Should handle renamed files correctly."""
        manager = HandoffManager(project_dir)

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "R  old_name.py -> new_name.py\n"

        with patch("claude_cortex.handoff.manager.subprocess.run", return_value=mock_result):
            files = manager._get_modified_files()

        assert "new_name.py" in files
        assert "old_name.py" not in files

    def test_get_modified_files_handles_timeout(self, project_dir):
        """Should return empty list on git timeout."""
        manager = HandoffManager(project_dir)

        with patch("claude_cortex.handoff.manager.subprocess.run", side_effect=subprocess.TimeoutExpired("git", 10)):
            files = manager._get_modified_files()

        assert files == []

    def test_get_modified_files_handles_missing_git(self, project_dir):
        """Should return empty list when git is not installed."""
        manager = HandoffManager(project_dir)

        with patch("claude_cortex.handoff.manager.subprocess.run", side_effect=FileNotFoundError()):
            files = manager._get_modified_files()

        assert files == []


class TestTaskExtraction:
    """Tests for task extraction from transcripts."""

    def test_extract_tasks_from_transcript_returns_empty_for_no_path(self, project_dir):
        """Should return empty lists when no transcript path provided."""
        manager = HandoffManager(project_dir)

        completed, pending = manager._extract_tasks_from_transcript()

        assert completed == []
        assert pending == []

    def test_extract_tasks_from_transcript_returns_empty_for_missing_file(self, project_dir):
        """Should return empty lists for non-existent transcript file."""
        manager = HandoffManager(project_dir)

        completed, pending = manager._extract_tasks_from_transcript(
            transcript_path="/nonexistent/path/transcript.json"
        )

        assert completed == []
        assert pending == []


class TestListHandoffs:
    """Tests for HandoffManager.list_handoffs method."""

    def test_list_handoffs_returns_metadata(self, project_dir):
        """Should return handoff metadata dictionaries."""
        manager = HandoffManager(project_dir)

        handoff = Handoff(
            session_id="test-session",
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
            completed_tasks=["Task 1", "Task 2"],
            pending_tasks=["Task 3"],
            blockers=["Blocker 1"],
            modified_files=["file1.py"],
        )
        manager.save_handoff(handoff)

        handoffs = manager.list_handoffs()

        assert len(handoffs) == 1
        assert handoffs[0]["session_id"] == "test-session"
        assert handoffs[0]["completed_count"] == 2
        assert handoffs[0]["pending_count"] == 1
        assert handoffs[0]["blocker_count"] == 1
        assert handoffs[0]["modified_files_count"] == 1

    def test_list_handoffs_returns_empty_when_no_handoffs(self, project_dir):
        """Should return empty list when no handoffs exist."""
        manager = HandoffManager(project_dir)

        handoffs = manager.list_handoffs()

        assert handoffs == []

    def test_list_handoffs_respects_limit(self, project_dir):
        """Should respect the limit parameter."""
        manager = HandoffManager(project_dir)

        # Create 5 handoffs
        for i in range(5):
            handoff = Handoff(
                session_id="test-session",
                timestamp=datetime(2024, 1, i + 1, 10, 0, 0, tzinfo=timezone.utc),
                completed_tasks=[f"Task {i}"],
            )
            manager.save_handoff(handoff)

        handoffs = manager.list_handoffs(limit=3)

        assert len(handoffs) == 3

    def test_list_handoffs_filters_by_session_id(self, project_dir):
        """Should filter by session_id when provided."""
        manager = HandoffManager(project_dir)

        handoff1 = Handoff(
            session_id="session-1",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            completed_tasks=["Session 1 task"],
        )
        handoff2 = Handoff(
            session_id="session-2",
            timestamp=datetime(2024, 1, 2, 10, 0, 0, tzinfo=timezone.utc),
            completed_tasks=["Session 2 task"],
        )
        manager.save_handoff(handoff1)
        manager.save_handoff(handoff2)

        handoffs = manager.list_handoffs(session_id="session-1")

        assert len(handoffs) == 1
        assert handoffs[0]["session_id"] == "session-1"


class TestGetHandoffContext:
    """Tests for HandoffManager.get_handoff_context method."""

    def test_get_handoff_context_includes_all_sections(self, project_dir):
        """Should generate context string with all handoff sections."""
        manager = HandoffManager(project_dir)

        handoff = Handoff(
            session_id="test-session",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            completed_tasks=["Completed task"],
            pending_tasks=["Pending task"],
            blockers=["A blocker"],
            modified_files=["file.py"],
            context_notes="Some notes",
        )

        context = manager.get_handoff_context(handoff)

        assert "## Previous Session Handoff" in context
        assert "test-session" in context
        assert "### Completed" in context
        assert "Completed task" in context
        assert "### Pending Tasks" in context
        assert "Pending task" in context
        assert "### Blockers" in context
        assert "A blocker" in context
        assert "### Recently Modified Files" in context
        assert "file.py" in context
        assert "### Context Notes" in context
        assert "Some notes" in context

    def test_get_handoff_context_omits_empty_sections(self, project_dir):
        """Should not include section headers for empty lists."""
        manager = HandoffManager(project_dir)

        handoff = Handoff(
            session_id="test-session",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            completed_tasks=["Only completed"],
        )

        context = manager.get_handoff_context(handoff)

        assert "### Completed" in context
        assert "### Pending" not in context
        assert "### Blockers" not in context
        assert "### Recently Modified" not in context
        assert "### Context" not in context

    def test_get_handoff_context_limits_modified_files(self, project_dir):
        """Should limit modified files to 10."""
        manager = HandoffManager(project_dir)

        many_files = [f"file{i}.py" for i in range(15)]
        handoff = Handoff(
            session_id="test-session",
            timestamp=datetime(2024, 1, 1, 10, 0, 0, tzinfo=timezone.utc),
            completed_tasks=["Task"],
            modified_files=many_files,
        )

        context = manager.get_handoff_context(handoff)

        # Count how many files are listed
        file_count = sum(1 for line in context.split("\n") if line.startswith("- file"))
        assert file_count == 10


class TestHandoffManagerInit:
    """Tests for HandoffManager initialization."""

    def test_init_with_project_path(self, project_dir):
        """Should use provided project path."""
        manager = HandoffManager(project_dir)

        assert manager.project_path == project_dir
        assert manager.handoffs_dir == project_dir / ".claude" / "handoffs"

    def test_init_defaults_to_cwd(self):
        """Should default to current working directory."""
        manager = HandoffManager()

        assert manager.project_path == Path.cwd()
