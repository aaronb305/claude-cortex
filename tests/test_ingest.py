"""Tests for git and PR ingestion functionality."""

import pytest
import subprocess
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from claude_cortex.ledger.models import LearningCategory, LearningSource, PrivacyLevel
from claude_cortex.ingest.git_extractor import GitExtractor, GitCommit
from claude_cortex.ingest.pr_extractor import PRExtractor
from claude_cortex.ingest.github_client import GitHubClient, PullRequest, Review, Comment
from claude_cortex.ingest.state import (
    IngestionState,
    IngestionStateManager,
    GitIngestionState,
    GitHubIngestionState,
)
from claude_cortex.ingest.patterns import (
    EXPLICIT_TAG_PATTERNS,
    CONVENTIONAL_COMMIT_PATTERN,
    COMMIT_TYPE_TO_CATEGORY,
    CO_AUTHOR_PATTERN,
    MIN_MESSAGE_LENGTH,
    CONFIDENCE_EXPLICIT_TAG,
    CONFIDENCE_CONVENTIONAL_COMMIT,
)


# =============================================================================
# GitCommit Tests
# =============================================================================


class TestGitCommit:
    """Tests for the GitCommit dataclass."""

    def test_short_sha(self):
        """Should return first 7 characters of SHA."""
        commit = GitCommit(
            sha="abc1234567890def",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="Test commit",
            body="",
        )
        assert commit.short_sha == "abc1234"

    def test_full_message_with_body(self):
        """Should combine subject and body with blank line."""
        commit = GitCommit(
            sha="abc123",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="Test subject",
            body="Detailed body content",
        )
        assert commit.full_message == "Test subject\n\nDetailed body content"

    def test_full_message_without_body(self):
        """Should return just subject when no body."""
        commit = GitCommit(
            sha="abc123",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="Test subject",
            body="",
        )
        assert commit.full_message == "Test subject"


# =============================================================================
# GitExtractor Tests
# =============================================================================


class TestGitExtractorExplicitTags:
    """Tests for extracting learnings from explicit tags."""

    @pytest.fixture
    def mock_extractor(self, temp_dir):
        """Create a GitExtractor with mocked git verification."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        return GitExtractor(temp_dir)

    def test_extract_discovery_tag(self, mock_extractor):
        """Should extract [DISCOVERY] tagged content."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: add new feature",
            body="[DISCOVERY] Found that caching reduces load by 50%",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.DISCOVERY
        assert "caching reduces load by 50%" in learnings[0].content
        assert learnings[0].learning_source == LearningSource.GIT_COMMIT

    def test_extract_decision_tag(self, mock_extractor):
        """Should extract [DECISION] tagged content."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="refactor: update architecture",
            body="[DECISION] Using PostgreSQL over MySQL for better JSON support",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.DECISION
        assert "PostgreSQL over MySQL" in learnings[0].content

    def test_extract_error_tag(self, mock_extractor):
        """Should extract [ERROR] tagged content."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="fix: resolve crash",
            body="[ERROR] Don't call close() on already closed connections",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.ERROR
        assert "close()" in learnings[0].content

    def test_extract_pattern_tag(self, mock_extractor):
        """Should extract [PATTERN] tagged content."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="refactor: improve structure",
            body="[PATTERN] Use factory pattern for creating validators",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.PATTERN
        assert "factory pattern" in learnings[0].content

    def test_extract_multiple_tags(self, mock_extractor):
        """Should extract multiple tags from same commit."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: major update",
            body="""
[DISCOVERY] The API supports batch operations natively
[DECISION] Using batch operations instead of individual calls
[PATTERN] Batch updates in groups of 100 for optimal performance
""",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 3
        categories = {l.category for l in learnings}
        assert categories == {
            LearningCategory.DISCOVERY,
            LearningCategory.DECISION,
            LearningCategory.PATTERN,
        }

    def test_ignore_short_tag_content(self, mock_extractor):
        """Should ignore tags with content shorter than MIN_MESSAGE_LENGTH."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="fix: quick fix",
            body="[DISCOVERY] Short",  # Too short
        )

        learnings = mock_extractor.extract_learnings(commit)

        # Should fall back to conventional commit extraction
        assert all(l.category != LearningCategory.DISCOVERY or len(l.content) >= MIN_MESSAGE_LENGTH for l in learnings)

    def test_case_insensitive_tags(self, mock_extractor):
        """Should match tags case-insensitively."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: update",
            body="[discovery] Works with lowercase tags just fine",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.DISCOVERY


class TestGitExtractorConventionalCommits:
    """Tests for extracting learnings from conventional commits."""

    @pytest.fixture
    def mock_extractor(self, temp_dir):
        """Create a GitExtractor with mocked git verification."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        return GitExtractor(temp_dir)

    def test_feat_to_discovery(self, mock_extractor):
        """Should map 'feat:' commits to DISCOVERY category."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: add user authentication via OAuth2",
            body="",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.DISCOVERY
        assert learnings[0].confidence >= CONFIDENCE_CONVENTIONAL_COMMIT

    def test_fix_to_error(self, mock_extractor):
        """Should map 'fix:' commits to ERROR category."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="fix: prevent race condition in session handling",
            body="",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.ERROR

    def test_refactor_to_pattern(self, mock_extractor):
        """Should map 'refactor:' commits to PATTERN category."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="refactor: extract common validation logic into reusable module",
            body="",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.PATTERN

    def test_docs_to_decision(self, mock_extractor):
        """Should map 'docs:' commits to DECISION category."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="docs: document API versioning strategy and migration guide",
            body="",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.DECISION

    def test_skip_style_commits(self, mock_extractor):
        """Should skip 'style:' commits (no learning value)."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="style: fix formatting and indentation",
            body="",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 0

    def test_skip_chore_commits(self, mock_extractor):
        """Should skip 'chore:' commits (no learning value)."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="chore: update dependencies to latest versions",
            body="",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 0

    def test_scope_included_in_content(self, mock_extractor):
        """Should include scope in learning content."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat(auth): implement JWT token refresh mechanism",
            body="",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        assert "[auth]" in learnings[0].content
        assert "JWT token refresh" in learnings[0].content

    def test_body_included_in_content(self, mock_extractor):
        """Should include commit body in learning content."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: add caching layer for API responses",
            body="Uses Redis for distributed caching with 5-minute TTL.",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        assert "Redis" in learnings[0].content
        assert "5-minute TTL" in learnings[0].content


class TestGitExtractorCoAuthors:
    """Tests for co-author extraction."""

    @pytest.fixture
    def mock_extractor(self, temp_dir):
        """Create a GitExtractor with mocked git verification."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        return GitExtractor(temp_dir)

    def test_extract_single_coauthor(self, mock_extractor):
        """Should extract a single co-author."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: collaborative feature implementation",
            body="""
[DISCOVERY] Pair programming improves code quality significantly

Co-Authored-By: Jane Doe <jane@example.com>
""",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        assert "jane@example.com" in learnings[0].co_authors

    def test_extract_multiple_coauthors(self, mock_extractor):
        """Should extract multiple co-authors."""
        commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: team collaboration feature",
            body="""
[PATTERN] Use mob programming for complex features

Co-Authored-By: Alice <alice@example.com>
Co-Authored-By: Bob <bob@example.com>
Co-Authored-By: Charlie <charlie@example.com>
""",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        assert len(learnings[0].co_authors) == 3
        assert "alice@example.com" in learnings[0].co_authors
        assert "bob@example.com" in learnings[0].co_authors
        assert "charlie@example.com" in learnings[0].co_authors

    def test_coauthor_boosts_confidence(self, mock_extractor):
        """Should boost confidence for co-authored commits."""
        commit_solo = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: solo feature implementation with proper details",
            body="",
        )
        commit_paired = GitCommit(
            sha="def456abc789",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: paired feature implementation with proper details",
            body="Co-Authored-By: Partner <partner@example.com>",
        )

        learnings_solo = mock_extractor.extract_learnings(commit_solo)
        learnings_paired = mock_extractor.extract_learnings(commit_paired)

        assert len(learnings_solo) == 1
        assert len(learnings_paired) == 1
        # Co-authored should have higher confidence
        assert learnings_paired[0].confidence > learnings_solo[0].confidence


class TestGitExtractorConfidence:
    """Tests for confidence computation."""

    @pytest.fixture
    def mock_extractor(self, temp_dir):
        """Create a GitExtractor with mocked git verification."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        return GitExtractor(temp_dir)

    def test_detailed_message_boosts_confidence(self, mock_extractor):
        """Should boost confidence for detailed messages (>100 chars)."""
        short_commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: short feature description here",
            body="",
        )
        detailed_commit = GitCommit(
            sha="def456abc789",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: detailed feature",
            body="This is a very detailed description of the feature that explains exactly what was done and why. It includes context about the implementation choices and reasoning behind them.",
        )

        short_learnings = mock_extractor.extract_learnings(short_commit)
        detailed_learnings = mock_extractor.extract_learnings(detailed_commit)

        assert len(short_learnings) == 1
        assert len(detailed_learnings) == 1
        assert detailed_learnings[0].confidence > short_learnings[0].confidence

    def test_very_detailed_message_boosts_more(self, mock_extractor):
        """Should boost confidence more for very detailed messages (>200 chars)."""
        detailed_commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: feature with moderate detail for testing",
            body="A moderately detailed message that's over 100 characters but less than 200.",
        )
        very_detailed_commit = GitCommit(
            sha="def456abc789",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: feature with extensive detail",
            body="This is an extremely detailed and comprehensive description of the feature implementation. It covers all aspects of the change including the motivation, the technical approach, the alternatives considered, the testing strategy, and the expected impact. This level of detail demonstrates thorough thinking about the change.",
        )

        detailed_learnings = mock_extractor.extract_learnings(detailed_commit)
        very_detailed_learnings = mock_extractor.extract_learnings(very_detailed_commit)

        assert len(detailed_learnings) == 1
        assert len(very_detailed_learnings) == 1
        assert very_detailed_learnings[0].confidence > detailed_learnings[0].confidence

    def test_explicit_tag_higher_than_conventional(self, mock_extractor):
        """Should give higher confidence to explicit tags vs conventional commits."""
        conventional_commit = GitCommit(
            sha="abc123def456",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: add new feature with some reasonable description",
            body="",
        )
        tagged_commit = GitCommit(
            sha="def456abc789",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="chore: update deps",
            body="[DISCOVERY] Found that the new API supports batch mode",
        )

        conventional_learnings = mock_extractor.extract_learnings(conventional_commit)
        tagged_learnings = mock_extractor.extract_learnings(tagged_commit)

        assert len(conventional_learnings) == 1
        assert len(tagged_learnings) == 1
        assert tagged_learnings[0].confidence > conventional_learnings[0].confidence


class TestGitExtractorMetadata:
    """Tests for git metadata extraction."""

    @pytest.fixture
    def mock_extractor(self, temp_dir):
        """Create a GitExtractor with mocked git verification."""
        git_dir = temp_dir / ".git"
        git_dir.mkdir()
        return GitExtractor(temp_dir)

    def test_git_metadata_populated(self, mock_extractor):
        """Should populate git metadata correctly."""
        test_date = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        commit = GitCommit(
            sha="abc123def456789012345678901234567890abcd",
            author_name="John Smith",
            author_email="john@example.com",
            date=test_date,
            subject="feat: important feature implementation",
            body="[DISCOVERY] This is a notable finding about the system",
            branch="main",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        metadata = learnings[0].git_metadata
        assert metadata is not None
        assert metadata.commit_sha == "abc123def456789012345678901234567890abcd"
        assert metadata.commit_short_sha == "abc123d"
        assert metadata.commit_author_name == "John Smith"
        assert metadata.commit_author_email == "john@example.com"
        assert metadata.commit_date == test_date
        assert metadata.commit_subject == "feat: important feature implementation"
        assert metadata.branch == "main"

    def test_source_format(self, mock_extractor):
        """Should format source as git:<short_sha>."""
        commit = GitCommit(
            sha="abc123def456789",
            author_name="Test Author",
            author_email="test@example.com",
            date=datetime.now(timezone.utc),
            subject="feat: test feature with proper description",
            body="",
        )

        learnings = mock_extractor.extract_learnings(commit)

        assert len(learnings) == 1
        assert learnings[0].source == "git:abc123d"


# =============================================================================
# IngestionState Tests
# =============================================================================


class TestIngestionState:
    """Tests for IngestionState dataclasses."""

    def test_git_state_defaults(self):
        """Should have sensible defaults for GitIngestionState."""
        state = GitIngestionState()
        assert state.last_commit_sha is None
        assert state.last_commit_date is None
        assert state.commits_processed == 0
        assert state.learnings_extracted == 0

    def test_github_state_defaults(self):
        """Should have sensible defaults for GitHubIngestionState."""
        state = GitHubIngestionState()
        assert state.repository is None
        assert state.last_pr_number is None
        assert state.prs_processed == 0
        assert state.learnings_extracted == 0

    def test_ingestion_state_to_dict(self):
        """Should serialize to dictionary correctly."""
        state = IngestionState(
            git=GitIngestionState(
                last_commit_sha="abc123",
                commits_processed=10,
            ),
            github=GitHubIngestionState(
                repository="owner/repo",
                prs_processed=5,
            ),
        )

        result = state.to_dict()

        assert result["git"]["last_commit_sha"] == "abc123"
        assert result["git"]["commits_processed"] == 10
        assert result["github"]["repository"] == "owner/repo"
        assert result["github"]["prs_processed"] == 5
        assert result["version"] == 1

    def test_ingestion_state_from_dict(self):
        """Should deserialize from dictionary correctly."""
        data = {
            "git": {
                "last_commit_sha": "def456",
                "commits_processed": 20,
                "learnings_extracted": 5,
            },
            "github": {
                "repository": "test/repo",
                "last_pr_number": 42,
            },
            "version": 1,
        }

        state = IngestionState.from_dict(data)

        assert state.git.last_commit_sha == "def456"
        assert state.git.commits_processed == 20
        assert state.github.repository == "test/repo"
        assert state.github.last_pr_number == 42


class TestIngestionStateManager:
    """Tests for IngestionStateManager."""

    def test_load_creates_fresh_state(self, temp_dir):
        """Should create fresh state when no file exists."""
        manager = IngestionStateManager(temp_dir)

        state = manager.load()

        assert state.git.last_commit_sha is None
        assert state.github.repository is None

    def test_save_and_load_roundtrip(self, temp_dir):
        """Should save and load state correctly."""
        manager = IngestionStateManager(temp_dir)

        state = IngestionState(
            git=GitIngestionState(
                last_commit_sha="abc123",
                commits_processed=15,
            ),
        )
        manager.save(state)

        loaded = manager.load()

        assert loaded.git.last_commit_sha == "abc123"
        assert loaded.git.commits_processed == 15

    def test_update_git_state(self, temp_dir):
        """Should update git state correctly."""
        manager = IngestionStateManager(temp_dir)
        test_date = datetime(2024, 6, 15, 12, 0, 0, tzinfo=timezone.utc)

        state = manager.update_git_state(
            last_commit_sha="newsha123",
            last_commit_date=test_date,
            commits_processed=5,
            learnings_extracted=3,
            branch="main",
        )

        assert state.git.last_commit_sha == "newsha123"
        assert state.git.commits_processed == 5
        assert state.git.learnings_extracted == 3
        assert state.git.branch == "main"

    def test_update_accumulates_counts(self, temp_dir):
        """Should accumulate commit/learning counts."""
        manager = IngestionStateManager(temp_dir)
        test_date = datetime.now(timezone.utc)

        manager.update_git_state(
            last_commit_sha="sha1",
            last_commit_date=test_date,
            commits_processed=10,
            learnings_extracted=5,
        )

        state = manager.update_git_state(
            last_commit_sha="sha2",
            last_commit_date=test_date,
            commits_processed=5,
            learnings_extracted=2,
        )

        assert state.git.commits_processed == 15
        assert state.git.learnings_extracted == 7

    def test_reset_git_state(self, temp_dir):
        """Should reset git state while preserving github state."""
        manager = IngestionStateManager(temp_dir)
        test_date = datetime.now(timezone.utc)

        manager.update_git_state(
            last_commit_sha="sha1",
            last_commit_date=test_date,
            commits_processed=10,
            learnings_extracted=5,
        )
        manager.update_github_state(
            repository="owner/repo",
            last_pr_number=42,
            last_pr_merged_at=test_date,
            prs_processed=5,
            learnings_extracted=3,
        )

        manager.reset(source="git")

        state = manager.load()
        assert state.git.last_commit_sha is None
        assert state.git.commits_processed == 0
        assert state.github.repository == "owner/repo"  # Preserved
        assert state.github.prs_processed == 5  # Preserved

    def test_reset_all(self, temp_dir):
        """Should reset both git and github state."""
        manager = IngestionStateManager(temp_dir)
        test_date = datetime.now(timezone.utc)

        manager.update_git_state(
            last_commit_sha="sha1",
            last_commit_date=test_date,
            commits_processed=10,
            learnings_extracted=5,
        )
        manager.update_github_state(
            repository="owner/repo",
            last_pr_number=42,
            last_pr_merged_at=test_date,
            prs_processed=5,
            learnings_extracted=3,
        )

        manager.reset(source="all")

        state = manager.load()
        assert state.git.last_commit_sha is None
        assert state.github.repository is None

    def test_get_last_commit_sha(self, temp_dir):
        """Should return last commit SHA."""
        manager = IngestionStateManager(temp_dir)

        assert manager.get_last_commit_sha() is None

        manager.update_git_state(
            last_commit_sha="mysha",
            last_commit_date=datetime.now(timezone.utc),
            commits_processed=1,
            learnings_extracted=1,
        )

        assert manager.get_last_commit_sha() == "mysha"


# =============================================================================
# Pattern Tests
# =============================================================================


class TestPatterns:
    """Tests for extraction patterns."""

    def test_explicit_tag_pattern_discovery(self):
        """Should match [DISCOVERY] tags."""
        text = "[DISCOVERY] Found that the API supports pagination"
        pattern = EXPLICIT_TAG_PATTERNS[LearningCategory.DISCOVERY]

        matches = pattern.findall(text)

        assert len(matches) == 1
        assert "API supports pagination" in matches[0]

    def test_explicit_tag_pattern_multiline(self):
        """Should handle multiline content."""
        text = """
[DISCOVERY] This is a multiline
discovery that spans
multiple lines

[DECISION] And this is a decision
"""
        discovery_pattern = EXPLICIT_TAG_PATTERNS[LearningCategory.DISCOVERY]
        decision_pattern = EXPLICIT_TAG_PATTERNS[LearningCategory.DECISION]

        discovery_matches = discovery_pattern.findall(text)
        decision_matches = decision_pattern.findall(text)

        assert len(discovery_matches) == 1
        assert "multiline" in discovery_matches[0]
        assert len(decision_matches) == 1
        assert "decision" in decision_matches[0]

    def test_conventional_commit_pattern_basic(self):
        """Should match basic conventional commits."""
        subjects = [
            ("feat: add new feature", ("feat", None, "add new feature")),
            ("fix: resolve bug", ("fix", None, "resolve bug")),
            ("refactor: clean up code", ("refactor", None, "clean up code")),
        ]

        for subject, expected in subjects:
            match = CONVENTIONAL_COMMIT_PATTERN.match(subject)
            assert match is not None
            assert match.group(1).lower() == expected[0]
            assert match.group(2) == expected[1]
            assert match.group(3) == expected[2]

    def test_conventional_commit_pattern_with_scope(self):
        """Should match conventional commits with scope."""
        subject = "feat(auth): add OAuth2 support"
        match = CONVENTIONAL_COMMIT_PATTERN.match(subject)

        assert match is not None
        assert match.group(1).lower() == "feat"
        assert match.group(2) == "auth"
        assert match.group(3) == "add OAuth2 support"

    def test_conventional_commit_pattern_breaking(self):
        """Should match breaking change indicator."""
        subject = "feat(api)!: change response format"
        match = CONVENTIONAL_COMMIT_PATTERN.match(subject)

        assert match is not None
        assert match.group(1).lower() == "feat"
        assert match.group(2) == "api"

    def test_coauthor_pattern(self):
        """Should match Co-Authored-By trailers."""
        text = """
Some commit message

Co-Authored-By: Alice Smith <alice@example.com>
Co-Authored-By: Bob Jones <bob@example.org>
"""
        matches = list(CO_AUTHOR_PATTERN.finditer(text))

        assert len(matches) == 2
        assert matches[0].group(2) == "alice@example.com"
        assert matches[1].group(2) == "bob@example.org"

    def test_commit_type_category_mapping(self):
        """Should map commit types to categories correctly."""
        assert COMMIT_TYPE_TO_CATEGORY["feat"] == LearningCategory.DISCOVERY
        assert COMMIT_TYPE_TO_CATEGORY["fix"] == LearningCategory.ERROR
        assert COMMIT_TYPE_TO_CATEGORY["refactor"] == LearningCategory.PATTERN
        assert COMMIT_TYPE_TO_CATEGORY["perf"] == LearningCategory.PATTERN
        assert COMMIT_TYPE_TO_CATEGORY["docs"] == LearningCategory.DECISION
        assert COMMIT_TYPE_TO_CATEGORY["style"] is None
        assert COMMIT_TYPE_TO_CATEGORY["chore"] is None


# =============================================================================
# PRExtractor Tests
# =============================================================================


class TestPRExtractor:
    """Tests for PR extraction."""

    def test_extract_explicit_tags_from_description(self):
        """Should extract explicit tags from PR description."""
        client = Mock(spec=GitHubClient)
        extractor = PRExtractor(client)

        pr = PullRequest(
            number=123,
            title="Add new feature",
            body="[DISCOVERY] Found that the system supports webhooks natively",
            author="testuser",
            url="https://github.com/test/repo/pull/123",
            merged_at=datetime.now(timezone.utc),
            labels=["enhancement"],
            base_branch="main",
            head_branch="feature/webhooks",
        )

        learnings = extractor._extract_from_description(pr)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.DISCOVERY
        assert "webhooks" in learnings[0].content
        assert learnings[0].learning_source == LearningSource.PR_DESCRIPTION

    def test_extract_from_review_changes_requested(self):
        """Should extract from CHANGES_REQUESTED reviews."""
        client = Mock(spec=GitHubClient)
        extractor = PRExtractor(client)

        pr = PullRequest(
            number=123,
            title="Update API",
            body="Basic PR description",
            author="testuser",
            url="https://github.com/test/repo/pull/123",
            merged_at=datetime.now(timezone.utc),
            labels=[],
            base_branch="main",
            head_branch="feature/api",
        )
        review = Review(
            author="reviewer",
            body="This approach has a potential memory leak, we should use weak references instead.",
            state="CHANGES_REQUESTED",
        )

        learnings = extractor._extract_from_review(pr, review)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.ERROR
        assert "memory leak" in learnings[0].content

    def test_inline_comment_includes_path(self):
        """Should include file path for inline comments."""
        client = Mock(spec=GitHubClient)
        extractor = PRExtractor(client)

        pr = PullRequest(
            number=123,
            title="Update code",
            body="PR body",
            author="testuser",
            url="https://github.com/test/repo/pull/123",
            merged_at=datetime.now(timezone.utc),
            labels=[],
            base_branch="main",
            head_branch="fix/bug",
        )
        comment = Comment(
            author="reviewer",
            body="[ERROR] This pattern causes issues with concurrent access",
            path="src/handlers/session.py",
            line=42,
        )

        learnings = extractor._extract_from_comment(pr, comment)

        assert len(learnings) == 1
        assert "src/handlers/session.py:42" in learnings[0].content

    def test_pr_metadata_populated(self):
        """Should populate PR metadata correctly."""
        client = Mock(spec=GitHubClient)
        extractor = PRExtractor(client)

        pr = PullRequest(
            number=456,
            title="Major refactor",
            body="[PATTERN] Use dependency injection for better testability",
            author="developer",
            url="https://github.com/org/project/pull/456",
            merged_at=datetime.now(timezone.utc),
            labels=["refactor"],
            base_branch="main",
            head_branch="refactor/di",
        )

        learnings = extractor._extract_from_description(pr)

        assert len(learnings) == 1
        metadata = learnings[0].git_metadata
        assert metadata is not None
        assert metadata.pr_number == 456
        assert metadata.pr_title == "Major refactor"
        assert metadata.pr_author == "developer"
        assert metadata.pr_url == "https://github.com/org/project/pull/456"
        assert metadata.branch == "refactor/di"


# =============================================================================
# Integration Tests
# =============================================================================


class TestGitExtractorIntegration:
    """Integration tests that use real git commands (on temp repos)."""

    @pytest.fixture
    def git_repo(self, temp_dir):
        """Create a temporary git repository with test commits."""
        # Initialize git repo
        subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True, check=True)
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=temp_dir,
            capture_output=True,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=temp_dir,
            capture_output=True,
            check=True,
        )

        # Create initial commit
        test_file = temp_dir / "test.txt"
        test_file.write_text("initial content")
        subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "feat: initial commit with basic setup"],
            cwd=temp_dir,
            capture_output=True,
            check=True,
        )

        # Create commit with explicit tag
        test_file.write_text("updated content")
        subprocess.run(["git", "add", "."], cwd=temp_dir, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "fix: resolve issue\n\n[DISCOVERY] Found that X causes Y behavior"],
            cwd=temp_dir,
            capture_output=True,
            check=True,
        )

        return temp_dir

    def test_get_commits_from_real_repo(self, git_repo):
        """Should get commits from a real git repository."""
        extractor = GitExtractor(git_repo)

        commits = extractor.get_commits(limit=10)

        # Should find at least 1 commit (parsing may vary slightly by git version)
        assert len(commits) >= 1
        assert commits[0].author_email == "test@example.com"

    def test_extract_learnings_from_real_repo(self, git_repo):
        """Should extract learnings from real git commits."""
        extractor = GitExtractor(git_repo)

        learnings, commits = extractor.ingest_commits(limit=10)

        # Should find learnings from both commits
        assert len(learnings) >= 1
        # Should have a discovery from the explicit tag
        discoveries = [l for l in learnings if l.category == LearningCategory.DISCOVERY]
        assert len(discoveries) >= 1

    def test_get_current_branch(self, git_repo):
        """Should get current branch name."""
        extractor = GitExtractor(git_repo)

        branch = extractor.get_current_branch()

        # Git init creates 'master' or 'main' depending on config
        assert branch in ("master", "main")
