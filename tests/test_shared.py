"""Tests for hooks/shared.py utilities."""

import pytest
from pathlib import Path
import sys

# Add hooks directory to path for import
hooks_path = Path(__file__).parent.parent / "hooks"
if str(hooks_path) not in sys.path:
    sys.path.insert(0, str(hooks_path))

from shared import (
    extract_learnings,
    is_valid_learning,
    save_handoff,
    load_latest_handoff,
    ExtractionSource,
    DEFAULT_SOURCE_CONFIDENCE,
    get_confidence_for_source,
)


class TestExtractLearnings:
    """Tests for extract_learnings function."""

    def test_extract_learnings_finds_tagged_learnings(self):
        """Should find learnings with proper tags."""
        text = """
        Here is some analysis.

        [DISCOVERY] The codebase uses a plugin architecture for extensions

        More text here.

        [PATTERN] Use dependency injection for better testability in services

        [ERROR] Never store passwords in plain text configuration files
        """

        learnings = extract_learnings(text)

        assert len(learnings) == 3

        categories = [l["category"] for l in learnings]
        assert "discovery" in categories
        assert "pattern" in categories
        assert "error" in categories

    def test_extract_learnings_handles_decision_tag(self):
        """Should find DECISION tagged learnings."""
        text = """
        After reviewing the options:

        [DECISION] We chose SQLite for local storage due to simplicity
        """

        learnings = extract_learnings(text)

        assert len(learnings) == 1
        assert learnings[0]["category"] == "decision"
        assert "SQLite" in learnings[0]["content"]

    def test_extract_learnings_ignores_short_content(self):
        """Should ignore learnings that are too short."""
        text = """
        [DISCOVERY] Short

        [PATTERN] This is a proper learning that has sufficient length to be valid
        """

        learnings = extract_learnings(text)

        # Only the longer learning should be extracted
        assert len(learnings) == 1
        assert "sufficient length" in learnings[0]["content"]

    def test_extract_learnings_deduplicates(self):
        """Should not return duplicate learnings."""
        text = """
        [DISCOVERY] The project uses pytest for testing across all modules

        Some other text.

        [DISCOVERY] The project uses pytest for testing across all modules
        """

        learnings = extract_learnings(text)

        assert len(learnings) == 1

    def test_extract_learnings_empty_text(self):
        """Should return empty list for empty text."""
        learnings = extract_learnings("")
        assert len(learnings) == 0

        learnings = extract_learnings("No tags here, just regular text.")
        assert len(learnings) == 0


class TestIsValidLearning:
    """Tests for is_valid_learning function."""

    def test_is_valid_learning_filters_empty(self):
        """Should reject empty content."""
        assert is_valid_learning("") is False
        assert is_valid_learning(None) is False

    def test_is_valid_learning_filters_markdown_tables(self):
        """Should reject content that looks like markdown tables."""
        table_content = "| Column 1 | Column 2 | Column 3 |"
        assert is_valid_learning(table_content) is False

    def test_is_valid_learning_filters_special_chars(self):
        """Should reject content with too many special characters."""
        special_content = "!@#$%^&*(){}[]<>?/\\"
        assert is_valid_learning(special_content) is False

    def test_is_valid_learning_filters_markdown_artifacts(self):
        """Should reject content starting with markdown formatting."""
        assert is_valid_learning("- list item") is False
        assert is_valid_learning("* another list") is False
        assert is_valid_learning("# heading") is False
        assert is_valid_learning("```code block") is False

    def test_is_valid_learning_filters_code_snippets(self):
        """Should reject content that looks like code."""
        code = "function(arg1, arg2, arg3, arg4)"
        assert is_valid_learning(code) is False

        code2 = "{ key: value, nested: { more: stuff } extra }"
        assert is_valid_learning(code2) is False

    def test_is_valid_learning_requires_words(self):
        """Should reject content without enough real words."""
        assert is_valid_learning("12 34 56") is False
        assert is_valid_learning("a b c") is False

    def test_is_valid_learning_accepts_valid_content(self):
        """Should accept proper learning content."""
        valid = "The project uses a modular architecture for extensibility"
        assert is_valid_learning(valid) is True

        valid2 = "Always validate user input before processing to prevent attacks"
        assert is_valid_learning(valid2) is True


class TestHandoffRoundtrip:
    """Tests for save_handoff and load_latest_handoff functions."""

    def test_save_handoff_creates_file(self, project_dir):
        """Should create a handoff file."""
        result = save_handoff(
            project_dir=project_dir,
            session_id="test-session-123",
            completed_tasks=["Implemented feature A"],
            pending_tasks=["Add tests for feature A"],
            blockers=[],
            modified_files=["src/feature.py"],
            context_notes="Working on the new feature",
        )

        assert result is not None
        assert result.exists()
        assert result.suffix == ".md"

    def test_save_and_load_roundtrip(self, project_dir):
        """Should roundtrip handoff data correctly."""
        original_data = {
            "session_id": "roundtrip-session",
            "completed_tasks": ["Task one completed", "Task two completed"],
            "pending_tasks": ["Task three pending"],
            "blockers": ["Waiting for API access"],
            "modified_files": ["file1.py", "file2.py"],
            "context_notes": "Important context for next session",
        }

        save_handoff(
            project_dir=project_dir,
            session_id=original_data["session_id"],
            completed_tasks=original_data["completed_tasks"],
            pending_tasks=original_data["pending_tasks"],
            blockers=original_data["blockers"],
            modified_files=original_data["modified_files"],
            context_notes=original_data["context_notes"],
        )

        loaded = load_latest_handoff(project_dir)

        assert loaded is not None
        assert loaded["session_id"] == original_data["session_id"]
        assert loaded["completed_tasks"] == original_data["completed_tasks"]
        assert loaded["pending_tasks"] == original_data["pending_tasks"]
        assert loaded["blockers"] == original_data["blockers"]
        assert loaded["modified_files"] == original_data["modified_files"]
        assert loaded["context_notes"] == original_data["context_notes"]

    def test_load_latest_handoff_returns_none_when_empty(self, project_dir):
        """Should return None when no handoffs exist."""
        loaded = load_latest_handoff(project_dir)
        assert loaded is None

    def test_load_latest_handoff_gets_most_recent(self, project_dir):
        """Should return the most recent handoff."""
        # Save first handoff
        save_handoff(
            project_dir=project_dir,
            session_id="session-1",
            completed_tasks=["First task"],
            pending_tasks=[],
            blockers=[],
            modified_files=[],
        )

        # Save second handoff (more recent)
        save_handoff(
            project_dir=project_dir,
            session_id="session-2",
            completed_tasks=["Second task"],
            pending_tasks=["Next task"],
            blockers=[],
            modified_files=[],
        )

        loaded = load_latest_handoff(project_dir)

        assert loaded is not None
        assert loaded["session_id"] == "session-2"
        assert "Second task" in loaded["completed_tasks"]

    def test_save_handoff_handles_empty_lists(self, project_dir):
        """Should handle empty task lists correctly."""
        save_handoff(
            project_dir=project_dir,
            session_id="empty-session",
            completed_tasks=[],
            pending_tasks=[],
            blockers=[],
            modified_files=[],
            context_notes="",
        )

        loaded = load_latest_handoff(project_dir)

        assert loaded is not None
        assert loaded["completed_tasks"] == []
        assert loaded["pending_tasks"] == []
        assert loaded["blockers"] == []
        assert loaded["modified_files"] == []


class TestExtractionSource:
    """Tests for ExtractionSource enum and confidence weighting."""

    def test_extraction_source_values(self):
        """Should have the correct source values."""
        assert ExtractionSource.USER_TAGGED.value == "user_tagged"
        assert ExtractionSource.STOP_HOOK.value == "stop_hook"
        assert ExtractionSource.LLM_ANALYSIS.value == "llm_analysis"
        assert ExtractionSource.CONSENSUS.value == "consensus"

    def test_default_source_confidence_values(self):
        """Should have correct default confidence values."""
        assert DEFAULT_SOURCE_CONFIDENCE[ExtractionSource.USER_TAGGED] == 0.70
        assert DEFAULT_SOURCE_CONFIDENCE[ExtractionSource.STOP_HOOK] == 0.50
        assert DEFAULT_SOURCE_CONFIDENCE[ExtractionSource.LLM_ANALYSIS] == 0.40
        assert DEFAULT_SOURCE_CONFIDENCE[ExtractionSource.CONSENSUS] == 0.85

    def test_get_confidence_for_source_defaults(self):
        """Should return default confidence when no settings provided."""
        assert get_confidence_for_source(ExtractionSource.USER_TAGGED) == 0.70
        assert get_confidence_for_source(ExtractionSource.STOP_HOOK) == 0.50
        assert get_confidence_for_source(ExtractionSource.LLM_ANALYSIS) == 0.40
        assert get_confidence_for_source(ExtractionSource.CONSENSUS) == 0.85

    def test_get_confidence_for_source_with_settings(self):
        """Should use settings values when provided."""
        settings = {
            "extraction": {
                "user_tagged_confidence": 0.80,
                "stop_hook_confidence": 0.60,
                "llm_analysis_confidence": 0.50,
                "consensus_confidence": 0.90,
            }
        }
        assert get_confidence_for_source(ExtractionSource.USER_TAGGED, settings) == 0.80
        assert get_confidence_for_source(ExtractionSource.STOP_HOOK, settings) == 0.60
        assert get_confidence_for_source(ExtractionSource.LLM_ANALYSIS, settings) == 0.50
        assert get_confidence_for_source(ExtractionSource.CONSENSUS, settings) == 0.90

    def test_get_confidence_for_source_partial_settings(self):
        """Should fall back to defaults for missing settings."""
        settings = {
            "extraction": {
                "user_tagged_confidence": 0.75,
                # Other values not provided
            }
        }
        assert get_confidence_for_source(ExtractionSource.USER_TAGGED, settings) == 0.75
        # These should use defaults
        assert get_confidence_for_source(ExtractionSource.STOP_HOOK, settings) == 0.50
        assert get_confidence_for_source(ExtractionSource.LLM_ANALYSIS, settings) == 0.40

    def test_extract_learnings_with_source_parameter(self):
        """Should use the source parameter for confidence weighting."""
        text = """
        [DISCOVERY] The codebase uses a plugin architecture for extensions
        """

        # Test with USER_TAGGED (default)
        learnings = extract_learnings(text, source=ExtractionSource.USER_TAGGED)
        assert len(learnings) == 1
        assert learnings[0]["confidence"] == 0.70
        assert learnings[0]["extraction_source"] == "user_tagged"

        # Test with STOP_HOOK
        learnings = extract_learnings(text, source=ExtractionSource.STOP_HOOK)
        assert len(learnings) == 1
        assert learnings[0]["confidence"] == 0.50
        assert learnings[0]["extraction_source"] == "stop_hook"

        # Test with LLM_ANALYSIS
        learnings = extract_learnings(text, source=ExtractionSource.LLM_ANALYSIS)
        assert len(learnings) == 1
        assert learnings[0]["confidence"] == 0.40
        assert learnings[0]["extraction_source"] == "llm_analysis"

    def test_extract_learnings_with_custom_settings(self):
        """Should respect custom confidence settings."""
        text = """
        [PATTERN] Use dependency injection for better testability
        """

        settings = {
            "extraction": {
                "user_tagged_confidence": 0.90,
            }
        }

        learnings = extract_learnings(
            text,
            source=ExtractionSource.USER_TAGGED,
            settings=settings
        )

        assert len(learnings) == 1
        assert learnings[0]["confidence"] == 0.90
        assert learnings[0]["extraction_source"] == "user_tagged"
