"""Ingestion state management for tracking processed commits and PRs."""

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


@dataclass
class GitIngestionState:
    """Tracks git commit ingestion progress."""

    last_commit_sha: Optional[str] = None
    last_commit_date: Optional[str] = None  # ISO format string
    last_ingested_at: Optional[str] = None  # ISO format string
    commits_processed: int = 0
    learnings_extracted: int = 0
    branch: Optional[str] = None


@dataclass
class GitHubIngestionState:
    """Tracks GitHub PR ingestion progress."""

    repository: Optional[str] = None
    last_pr_number: Optional[int] = None
    last_pr_merged_at: Optional[str] = None  # ISO format string
    last_ingested_at: Optional[str] = None   # ISO format string
    prs_processed: int = 0
    learnings_extracted: int = 0


@dataclass
class IngestionState:
    """Combined ingestion state for a project."""

    git: GitIngestionState = field(default_factory=GitIngestionState)
    github: GitHubIngestionState = field(default_factory=GitHubIngestionState)
    version: int = 1

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "git": asdict(self.git),
            "github": asdict(self.github),
            "version": self.version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "IngestionState":
        """Create from dictionary."""
        git_data = data.get("git", {})
        github_data = data.get("github", {})

        return cls(
            git=GitIngestionState(**git_data) if git_data else GitIngestionState(),
            github=GitHubIngestionState(**github_data) if github_data else GitHubIngestionState(),
            version=data.get("version", 1),
        )


class IngestionStateManager:
    """Manages ingestion state persistence for a project."""

    STATE_FILENAME = "ingestion_state.json"

    def __init__(self, project_path: Path):
        """Initialize state manager for a project.

        Args:
            project_path: Path to the project root directory
        """
        self.project_path = Path(project_path)
        self.claude_dir = self.project_path / ".claude"
        self.state_file = self.claude_dir / self.STATE_FILENAME

    def load(self) -> IngestionState:
        """Load state from disk.

        Returns:
            IngestionState: The loaded state, or a fresh state if none exists
        """
        if not self.state_file.exists():
            return IngestionState()

        try:
            with open(self.state_file) as f:
                data = json.load(f)
            return IngestionState.from_dict(data)
        except (json.JSONDecodeError, IOError):
            return IngestionState()

    def save(self, state: IngestionState) -> None:
        """Save state to disk.

        Args:
            state: The ingestion state to save
        """
        self.claude_dir.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, "w") as f:
            json.dump(state.to_dict(), f, indent=2)

    def update_git_state(
        self,
        last_commit_sha: str,
        last_commit_date: datetime,
        commits_processed: int,
        learnings_extracted: int,
        branch: Optional[str] = None,
    ) -> IngestionState:
        """Update git ingestion state after processing commits.

        Args:
            last_commit_sha: SHA of the last processed commit
            last_commit_date: Timestamp of the last processed commit
            commits_processed: Number of commits processed in this run
            learnings_extracted: Number of learnings extracted in this run
            branch: Branch that was processed

        Returns:
            The updated state
        """
        state = self.load()

        state.git.last_commit_sha = last_commit_sha
        state.git.last_commit_date = last_commit_date.isoformat()
        state.git.last_ingested_at = datetime.now(timezone.utc).isoformat()
        state.git.commits_processed += commits_processed
        state.git.learnings_extracted += learnings_extracted
        if branch:
            state.git.branch = branch

        self.save(state)
        return state

    def update_github_state(
        self,
        repository: str,
        last_pr_number: int,
        last_pr_merged_at: Optional[datetime],
        prs_processed: int,
        learnings_extracted: int,
    ) -> IngestionState:
        """Update GitHub PR ingestion state after processing PRs.

        Args:
            repository: Repository in owner/repo format
            last_pr_number: Number of the last processed PR
            last_pr_merged_at: Merge timestamp of the last processed PR
            prs_processed: Number of PRs processed in this run
            learnings_extracted: Number of learnings extracted in this run

        Returns:
            The updated state
        """
        state = self.load()

        state.github.repository = repository
        state.github.last_pr_number = last_pr_number
        state.github.last_pr_merged_at = (
            last_pr_merged_at.isoformat() if last_pr_merged_at else None
        )
        state.github.last_ingested_at = datetime.now(timezone.utc).isoformat()
        state.github.prs_processed += prs_processed
        state.github.learnings_extracted += learnings_extracted

        self.save(state)
        return state

    def reset(self, source: str = "all") -> None:
        """Reset ingestion state.

        Args:
            source: Which source to reset - "git", "github", or "all"
        """
        state = self.load()

        if source in ("git", "all"):
            state.git = GitIngestionState()
        if source in ("github", "all"):
            state.github = GitHubIngestionState()

        self.save(state)

    def get_last_commit_sha(self) -> Optional[str]:
        """Get the SHA of the last ingested commit."""
        state = self.load()
        return state.git.last_commit_sha

    def get_last_pr_number(self) -> Optional[int]:
        """Get the number of the last ingested PR."""
        state = self.load()
        return state.github.last_pr_number
