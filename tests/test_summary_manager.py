"""Tests for the SummaryManager class."""

import json
import pytest
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from claude_cortex.summaries.manager import SummaryManager
from claude_cortex.summaries.models import Summary


class TestSummaryCreation:
    """Tests for SummaryManager.create_summary method."""

    def test_create_summary_with_required_fields(self, project_dir):
        """Should create a summary with required fields."""
        manager = SummaryManager(project_path=project_dir)

        summary = manager.create_summary(
            session_id="test-session-123",
            summary_text="Implemented authentication feature",
        )

        assert summary.session_id == "test-session-123"
        assert summary.summary_text == "Implemented authentication feature"
        assert isinstance(summary.timestamp, datetime)

    def test_create_summary_captures_timestamp(self, project_dir):
        """Should capture current UTC timestamp."""
        manager = SummaryManager(project_path=project_dir)

        before = datetime.now(timezone.utc)
        summary = manager.create_summary(
            session_id="test-session",
            summary_text="Test summary",
        )
        after = datetime.now(timezone.utc)

        # Timestamp should be between before and after
        assert before <= summary.timestamp <= after

    def test_create_summary_with_explicit_learning_ids(self, project_dir):
        """Should include provided learning IDs."""
        manager = SummaryManager(project_path=project_dir)

        learning_ids = ["abc123", "def456", "ghi789"]
        summary = manager.create_summary(
            session_id="test-session",
            summary_text="Test summary",
            learning_ids=learning_ids,
        )

        assert summary.learning_ids == learning_ids

    def test_create_summary_with_explicit_files(self, project_dir):
        """Should include provided files list."""
        manager = SummaryManager(project_path=project_dir)

        files = ["src/main.py", "tests/test_main.py"]
        summary = manager.create_summary(
            session_id="test-session",
            summary_text="Test summary",
            files_discussed=files,
        )

        assert summary.files_discussed == files

    def test_create_summary_with_explicit_decisions(self, project_dir):
        """Should include provided decisions list."""
        manager = SummaryManager(project_path=project_dir)

        decisions = ["Use pytest for testing", "Add type hints"]
        summary = manager.create_summary(
            session_id="test-session",
            summary_text="Test summary",
            key_decisions=decisions,
        )

        assert summary.key_decisions == decisions

    def test_create_summary_extracts_decisions_from_text(self, project_dir):
        """Should extract decisions when assistant_text is provided."""
        manager = SummaryManager(project_path=project_dir)

        assistant_text = """
        I've decided to use pytest for the test framework.
        The approach is to implement modular components.
        """

        summary = manager.create_summary(
            session_id="test-session",
            summary_text="Test summary",
            assistant_text=assistant_text,
        )

        assert len(summary.key_decisions) > 0
        assert any("pytest" in d.lower() for d in summary.key_decisions)

    def test_create_summary_extracts_files_from_text(self, project_dir):
        """Should extract files when assistant_text is provided."""
        manager = SummaryManager(project_path=project_dir)

        assistant_text = """
        I'm reading `config.py` to understand the settings.
        I wrote to the file src/utils.py with the helper functions.
        """

        summary = manager.create_summary(
            session_id="test-session",
            summary_text="Test summary",
            assistant_text=assistant_text,
        )

        assert len(summary.files_discussed) > 0

    def test_create_summary_defaults_empty_lists(self, project_dir):
        """Should default to empty lists when no data provided."""
        manager = SummaryManager(project_path=project_dir)

        summary = manager.create_summary(
            session_id="test-session",
            summary_text="Test summary",
        )

        assert summary.key_decisions == []
        assert summary.files_discussed == []
        assert summary.learning_ids == []


class TestSummarySaving:
    """Tests for SummaryManager.save_summary method."""

    def test_save_summary_writes_to_correct_path(self, project_dir):
        """Should write summary to correct directory structure."""
        manager = SummaryManager(project_path=project_dir)

        summary = manager.create_summary(
            session_id="session-abc",
            summary_text="Test summary content",
        )

        file_path = manager.save_summary(summary)

        assert file_path.exists()
        assert file_path.parent.name == "session-abc"
        assert file_path.parent.parent.name == "summaries"
        assert file_path.name.startswith("summary-")
        assert file_path.suffix == ".json"

    def test_save_summary_creates_directories(self, project_dir):
        """Should create directories if they don't exist."""
        manager = SummaryManager(project_path=project_dir)

        # Ensure the summaries directory doesn't exist yet
        summaries_dir = project_dir / ".claude" / "summaries"
        assert not summaries_dir.exists()

        summary = manager.create_summary(
            session_id="new-session",
            summary_text="Test summary",
        )

        file_path = manager.save_summary(summary)

        assert file_path.exists()
        assert summaries_dir.exists()

    def test_save_summary_writes_valid_json(self, project_dir):
        """Should write properly formatted JSON."""
        manager = SummaryManager(project_path=project_dir)

        summary = manager.create_summary(
            session_id="test-session",
            summary_text="Test summary content",
            key_decisions=["Decision 1"],
            files_discussed=["file.py"],
            learning_ids=["learning-1"],
        )

        file_path = manager.save_summary(summary)

        with open(file_path) as f:
            data = json.load(f)

        assert data["session_id"] == "test-session"
        assert data["summary_text"] == "Test summary content"
        assert data["key_decisions"] == ["Decision 1"]
        assert data["files_discussed"] == ["file.py"]
        assert data["learning_ids"] == ["learning-1"]
        assert "timestamp" in data

    def test_save_summary_filename_contains_timestamp(self, project_dir):
        """Should include timestamp in filename."""
        manager = SummaryManager(project_path=project_dir)

        summary = manager.create_summary(
            session_id="test-session",
            summary_text="Test summary",
        )

        file_path = manager.save_summary(summary)

        # Filename format: summary-YYYYMMDD-HHMMSS.json
        assert file_path.name.startswith("summary-")
        timestamp_part = file_path.stem.replace("summary-", "")
        # Should have format like 20240115-143022
        assert "-" in timestamp_part
        date_part, time_part = timestamp_part.split("-")
        assert len(date_part) == 8  # YYYYMMDD
        assert len(time_part) == 6  # HHMMSS


class TestSummaryLoading:
    """Tests for SummaryManager loading methods."""

    def test_load_latest_summary_finds_most_recent(self, project_dir):
        """Should find the most recent summary."""
        manager = SummaryManager(project_path=project_dir)

        # Create multiple summaries with different timestamps to ensure ordering
        # Use explicit timestamps to avoid race conditions
        base_time = datetime.now(timezone.utc)

        summary1 = Summary(
            session_id="session-1",
            timestamp=base_time - timedelta(seconds=2),
            summary_text="First summary",
        )
        manager.save_summary(summary1)

        summary2 = Summary(
            session_id="session-2",
            timestamp=base_time - timedelta(seconds=1),
            summary_text="Second summary",
        )
        manager.save_summary(summary2)

        summary3 = Summary(
            session_id="session-3",
            timestamp=base_time,
            summary_text="Third summary",
        )
        manager.save_summary(summary3)

        latest = manager.load_latest_summary()

        assert latest is not None
        assert latest.summary_text == "Third summary"
        assert latest.session_id == "session-3"

    def test_load_latest_summary_returns_none_when_none_exist(self, project_dir):
        """Should return None when no summaries exist."""
        manager = SummaryManager(project_path=project_dir)

        latest = manager.load_latest_summary()

        assert latest is None

    def test_load_latest_summary_handles_missing_directory(self, project_dir):
        """Should handle missing summaries directory gracefully."""
        manager = SummaryManager(project_path=project_dir)

        # Don't create the summaries directory
        assert not manager.summaries_dir.exists()

        latest = manager.load_latest_summary()

        assert latest is None

    def test_load_latest_summary_filters_by_session(self, project_dir):
        """Should filter by session_id when provided."""
        manager = SummaryManager(project_path=project_dir)

        # Create summaries in different sessions
        summary1 = manager.create_summary(
            session_id="session-a",
            summary_text="Summary A",
        )
        manager.save_summary(summary1)

        summary2 = manager.create_summary(
            session_id="session-b",
            summary_text="Summary B",
        )
        manager.save_summary(summary2)

        latest_a = manager.load_latest_summary(session_id="session-a")

        assert latest_a is not None
        assert latest_a.session_id == "session-a"
        assert latest_a.summary_text == "Summary A"

    def test_load_summary_from_path(self, project_dir):
        """Should load a summary from a specific file path."""
        manager = SummaryManager(project_path=project_dir)

        original = manager.create_summary(
            session_id="test-session",
            summary_text="Test content",
            key_decisions=["Decision 1", "Decision 2"],
        )
        file_path = manager.save_summary(original)

        loaded = manager.load_summary(file_path)

        assert loaded is not None
        assert loaded.session_id == original.session_id
        assert loaded.summary_text == original.summary_text
        assert loaded.key_decisions == original.key_decisions

    def test_load_summary_returns_none_for_invalid_file(self, project_dir):
        """Should return None for non-existent file."""
        manager = SummaryManager(project_path=project_dir)

        result = manager.load_summary(project_dir / "nonexistent.json")

        assert result is None

    def test_load_summary_handles_corrupted_json(self, project_dir):
        """Should handle corrupted JSON gracefully."""
        manager = SummaryManager(project_path=project_dir)

        # Create a corrupted JSON file
        corrupt_path = project_dir / "corrupt.json"
        corrupt_path.write_text("{ invalid json }")

        result = manager.load_summary(corrupt_path)

        assert result is None

    def test_load_recent_summaries_returns_multiple(self, project_dir):
        """Should return multiple recent summaries."""
        manager = SummaryManager(project_path=project_dir)

        # Create 5 summaries with explicit timestamps to ensure ordering
        base_time = datetime.now(timezone.utc)
        for i in range(5):
            summary = Summary(
                session_id=f"session-{i}",
                timestamp=base_time + timedelta(seconds=i),
                summary_text=f"Summary {i}",
            )
            manager.save_summary(summary)

        recent = manager.load_recent_summaries(limit=3)

        assert len(recent) == 3
        # Should be in reverse order (newest first)
        assert recent[0].summary_text == "Summary 4"
        assert recent[1].summary_text == "Summary 3"
        assert recent[2].summary_text == "Summary 2"

    def test_load_recent_summaries_respects_limit(self, project_dir):
        """Should respect the limit parameter."""
        manager = SummaryManager(project_path=project_dir)

        for i in range(10):
            summary = manager.create_summary(
                session_id=f"session-{i}",
                summary_text=f"Summary {i}",
            )
            manager.save_summary(summary)

        recent = manager.load_recent_summaries(limit=2)

        assert len(recent) == 2

    def test_load_recent_summaries_empty_when_none_exist(self, project_dir):
        """Should return empty list when no summaries exist."""
        manager = SummaryManager(project_path=project_dir)

        recent = manager.load_recent_summaries()

        assert recent == []


class TestTextExtraction:
    """Tests for text extraction methods."""

    def test_extract_decisions_finds_decided_to(self, project_dir):
        """Should find 'decided to' patterns."""
        manager = SummaryManager(project_path=project_dir)

        text = "I decided to use pytest for testing. It's the best choice."
        decisions = manager.extract_decisions_from_text(text)

        assert len(decisions) >= 1
        assert any("pytest" in d.lower() for d in decisions)

    def test_extract_decisions_finds_decision_tag(self, project_dir):
        """Should find [DECISION] tags."""
        manager = SummaryManager(project_path=project_dir)

        text = "[DECISION] Use FastAPI instead of Flask for better async support."
        decisions = manager.extract_decisions_from_text(text)

        assert len(decisions) >= 1
        assert any("fastapi" in d.lower() for d in decisions)

    def test_extract_decisions_finds_chose_to(self, project_dir):
        """Should find 'chose to' patterns."""
        manager = SummaryManager(project_path=project_dir)

        text = "I chose to implement caching for performance reasons."
        decisions = manager.extract_decisions_from_text(text)

        assert len(decisions) >= 1
        assert any("caching" in d.lower() for d in decisions)

    def test_extract_decisions_finds_approach_is(self, project_dir):
        """Should find 'approach is to' patterns."""
        manager = SummaryManager(project_path=project_dir)

        text = "The approach is to use dependency injection throughout."
        decisions = manager.extract_decisions_from_text(text)

        assert len(decisions) >= 1
        assert any("dependency" in d.lower() for d in decisions)

    def test_extract_decisions_finds_going_with(self, project_dir):
        """Should find 'going with' patterns."""
        manager = SummaryManager(project_path=project_dir)

        text = "I'm going with a microservices architecture for scalability."
        decisions = manager.extract_decisions_from_text(text)

        assert len(decisions) >= 1
        assert any("microservices" in d.lower() for d in decisions)

    def test_extract_decisions_handles_empty_text(self, project_dir):
        """Should handle empty text gracefully."""
        manager = SummaryManager(project_path=project_dir)

        decisions = manager.extract_decisions_from_text("")

        assert decisions == []

    def test_extract_decisions_deduplicates(self, project_dir):
        """Should not return duplicate decisions."""
        manager = SummaryManager(project_path=project_dir)

        text = """
        I decided to use pytest for testing.
        As I mentioned, I decided to use pytest for testing.
        """
        decisions = manager.extract_decisions_from_text(text)

        # Should not have duplicate "use pytest for testing"
        lowercase_decisions = [d.lower() for d in decisions]
        assert len(lowercase_decisions) == len(set(lowercase_decisions))

    def test_extract_decisions_limits_to_ten(self, project_dir):
        """Should limit results to 10 decisions."""
        manager = SummaryManager(project_path=project_dir)

        # Create text with many decisions
        text = "\n".join(
            f"I decided to implement feature {i} for the project."
            for i in range(20)
        )
        decisions = manager.extract_decisions_from_text(text)

        assert len(decisions) <= 10

    def test_extract_decisions_filters_short_matches(self, project_dir):
        """Should filter out very short matches."""
        manager = SummaryManager(project_path=project_dir)

        text = "I decided to do it."
        decisions = manager.extract_decisions_from_text(text)

        # "do it" is too short (< 15 chars) and should be filtered
        assert not any(len(d) < 15 for d in decisions)

    def test_extract_files_finds_reading_patterns(self, project_dir):
        """Should find files mentioned with 'reading'."""
        manager = SummaryManager(project_path=project_dir)

        text = "I'm reading config.py to understand the settings."
        files = manager.extract_files_from_text(text)

        assert "config.py" in files

    def test_extract_files_finds_wrote_patterns(self, project_dir):
        """Should find files mentioned with 'wrote'."""
        manager = SummaryManager(project_path=project_dir)

        text = "I wrote src/utils.py with helper functions."
        files = manager.extract_files_from_text(text)

        assert any("utils.py" in f for f in files)

    def test_extract_files_finds_backtick_quoted(self, project_dir):
        """Should find files in backticks."""
        manager = SummaryManager(project_path=project_dir)

        text = "The file `main.py` contains the entry point."
        files = manager.extract_files_from_text(text)

        assert "main.py" in files

    def test_extract_files_handles_empty_text(self, project_dir):
        """Should handle empty text gracefully."""
        manager = SummaryManager(project_path=project_dir)

        files = manager.extract_files_from_text("")

        assert files == []

    def test_extract_files_filters_urls(self, project_dir):
        """Should filter out HTTP URLs."""
        manager = SummaryManager(project_path=project_dir)

        text = "See https://example.com/file.py for reference."
        files = manager.extract_files_from_text(text)

        # Should not include the URL as a file
        assert not any("example.com" in f for f in files)

    def test_extract_files_limits_to_thirty(self, project_dir):
        """Should limit results to 30 files."""
        manager = SummaryManager(project_path=project_dir)

        # Create text with many files
        text = " ".join(f"`file{i}.py`" for i in range(50))
        files = manager.extract_files_from_text(text)

        assert len(files) <= 30

    def test_extract_files_returns_sorted(self, project_dir):
        """Should return files in sorted order."""
        manager = SummaryManager(project_path=project_dir)

        text = "`zebra.py` `alpha.py` `middle.py`"
        files = manager.extract_files_from_text(text)

        assert files == sorted(files)


class TestSummaryListAndContext:
    """Tests for listing summaries and generating context."""

    def test_list_summaries_returns_metadata(self, project_dir):
        """Should return summary metadata."""
        manager = SummaryManager(project_path=project_dir)

        summary = manager.create_summary(
            session_id="test-session",
            summary_text="Test summary content",
            key_decisions=["Decision 1", "Decision 2"],
            files_discussed=["file1.py", "file2.py", "file3.py"],
            learning_ids=["learning-1"],
        )
        manager.save_summary(summary)

        summaries = manager.list_summaries()

        assert len(summaries) == 1
        assert summaries[0]["session_id"] == "test-session"
        assert summaries[0]["decisions_count"] == 2
        assert summaries[0]["files_count"] == 3
        assert summaries[0]["learnings_count"] == 1
        assert "timestamp" in summaries[0]
        assert "file_path" in summaries[0]

    def test_list_summaries_empty_when_none(self, project_dir):
        """Should return empty list when no summaries exist."""
        manager = SummaryManager(project_path=project_dir)

        summaries = manager.list_summaries()

        assert summaries == []

    def test_list_summaries_filters_by_session(self, project_dir):
        """Should filter by session_id when provided."""
        manager = SummaryManager(project_path=project_dir)

        # Create summaries with explicit timestamps to avoid overwrites
        base_time = datetime.now(timezone.utc)
        sessions = ["session-a", "session-b", "session-a"]
        for i, session in enumerate(sessions):
            summary = Summary(
                session_id=session,
                timestamp=base_time + timedelta(seconds=i),
                summary_text=f"Summary {i} for {session}",
            )
            manager.save_summary(summary)

        summaries = manager.list_summaries(session_id="session-a")

        assert len(summaries) == 2
        assert all(s["session_id"] == "session-a" for s in summaries)

    def test_list_summaries_respects_limit(self, project_dir):
        """Should respect the limit parameter."""
        manager = SummaryManager(project_path=project_dir)

        for i in range(10):
            summary = manager.create_summary(
                session_id=f"session-{i}",
                summary_text=f"Summary {i}",
            )
            manager.save_summary(summary)

        summaries = manager.list_summaries(limit=5)

        assert len(summaries) == 5

    def test_get_context_for_session_generates_markdown(self, project_dir):
        """Should generate markdown context for session."""
        manager = SummaryManager(project_path=project_dir)

        summary = manager.create_summary(
            session_id="test-session",
            summary_text="Implemented feature X",
            key_decisions=["Use pytest"],
            files_discussed=["main.py"],
        )
        manager.save_summary(summary)

        context = manager.get_context_for_session()

        assert "## Recent Session Summaries" in context
        # Session ID is truncated to 8 chars in format_for_context
        assert "test-ses" in context
        assert "Implemented feature X" in context

    def test_get_context_for_session_empty_when_no_summaries(self, project_dir):
        """Should return empty string when no summaries exist."""
        manager = SummaryManager(project_path=project_dir)

        context = manager.get_context_for_session()

        assert context == ""

    def test_get_context_for_session_respects_limit(self, project_dir):
        """Should respect the limit parameter."""
        manager = SummaryManager(project_path=project_dir)

        for i in range(10):
            summary = manager.create_summary(
                session_id=f"session-{i}",
                summary_text=f"Summary {i}",
            )
            manager.save_summary(summary)

        context = manager.get_context_for_session(limit=2)

        # Should only contain 2 session references
        assert context.count("### Session") == 2


class TestManagerInitialization:
    """Tests for SummaryManager initialization."""

    def test_init_with_project_path(self, project_dir):
        """Should initialize with provided project path."""
        manager = SummaryManager(project_path=project_dir)

        assert manager.project_path == project_dir
        assert manager.summaries_dir == project_dir / ".claude" / "summaries"

    def test_init_defaults_to_cwd(self):
        """Should default to current working directory."""
        manager = SummaryManager()

        assert manager.project_path == Path.cwd()

    def test_ensure_summaries_dir_creates_structure(self, project_dir):
        """Should create the full directory structure."""
        manager = SummaryManager(project_path=project_dir)

        session_dir = manager._ensure_summaries_dir("test-session")

        assert session_dir.exists()
        assert session_dir.name == "test-session"
        assert session_dir.parent.name == "summaries"
        assert session_dir.parent.parent.name == ".claude"
