"""Git and PR ingestion for learning extraction."""

from claude_cortex.ingest.state import (
    IngestionState,
    IngestionStateManager,
    GitIngestionState,
    GitHubIngestionState,
)
from claude_cortex.ingest.git_extractor import GitExtractor, GitCommit
from claude_cortex.ingest.github_client import (
    GitHubClient,
    PullRequest,
    Review,
    Comment,
)
from claude_cortex.ingest.pr_extractor import PRExtractor
from claude_cortex.ingest.patterns import (
    EXPLICIT_TAG_PATTERNS,
    CONVENTIONAL_COMMIT_PATTERN,
    COMMIT_TYPE_TO_CATEGORY,
    CO_AUTHOR_PATTERN,
)

__all__ = [
    # State management
    "IngestionState",
    "IngestionStateManager",
    "GitIngestionState",
    "GitHubIngestionState",
    # Git extraction
    "GitExtractor",
    "GitCommit",
    # GitHub/PR extraction
    "GitHubClient",
    "PullRequest",
    "Review",
    "Comment",
    "PRExtractor",
    # Patterns
    "EXPLICIT_TAG_PATTERNS",
    "CONVENTIONAL_COMMIT_PATTERN",
    "COMMIT_TYPE_TO_CATEGORY",
    "CO_AUTHOR_PATTERN",
]
