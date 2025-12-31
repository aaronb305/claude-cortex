"""Data models for the ledger system."""

import hashlib
import json
import re
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field


def compute_content_hash(content: str) -> str:
    """Compute a normalized content hash for deduplication.

    Normalizes the content by:
    - Converting to lowercase
    - Stripping leading/trailing whitespace
    - Normalizing internal whitespace (multiple spaces/newlines become single space)

    Args:
        content: The content string to hash

    Returns:
        First 16 characters of the SHA-256 hash
    """
    # Normalize: lowercase, strip, collapse whitespace
    normalized = content.lower().strip()
    normalized = re.sub(r'\s+', ' ', normalized)

    # Compute SHA-256 and return first 16 chars
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


class LearningCategory(str, Enum):
    """Categories of knowledge that can be learned."""

    DISCOVERY = "discovery"  # New information about codebase, APIs, patterns
    DECISION = "decision"    # Architectural choices, tradeoffs, rationale
    ERROR = "error"          # Mistakes to avoid, failed approaches, gotchas
    PATTERN = "pattern"      # Reusable solutions, templates, conventions


class PrivacyLevel(str, Enum):
    """Privacy levels for learnings."""

    PUBLIC = "public"      # Normal learning, can be promoted to global
    PROJECT = "project"    # Stays in project ledger only
    PRIVATE = "private"    # Never persisted (filtered before storage)
    REDACTED = "redacted"  # Logged as redacted (content replaced)


class OutcomeResult(str, Enum):
    """Result of applying knowledge."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


class LearningSource(str, Enum):
    """Source of the learning extraction."""

    SESSION = "session"              # Claude Code session transcript
    GIT_COMMIT = "git_commit"        # Git commit message
    GIT_DIFF = "git_diff"            # Git diff analysis
    PR_DESCRIPTION = "pr_description"  # Pull request description
    PR_REVIEW = "pr_review"          # Pull request review comment
    PR_COMMENT = "pr_comment"        # Pull request discussion comment
    MANUAL = "manual"                # Manually added via CLI
    IMPORT = "import"                # Imported from another ledger


class GitSourceMetadata(BaseModel):
    """Metadata for git-sourced learnings."""

    commit_sha: Optional[str] = Field(default=None, description="Full commit SHA")
    commit_short_sha: Optional[str] = Field(default=None, description="First 7 chars of SHA")
    commit_author_name: Optional[str] = Field(default=None, description="Commit author name")
    commit_author_email: Optional[str] = Field(default=None, description="Commit author email")
    commit_date: Optional[datetime] = Field(default=None, description="Commit timestamp")
    commit_subject: Optional[str] = Field(default=None, description="First line of commit message")
    branch: Optional[str] = Field(default=None, description="Branch name")
    repository: Optional[str] = Field(default=None, description="Repository path or URL")

    # PR-specific fields
    pr_number: Optional[int] = Field(default=None, description="Pull request number")
    pr_title: Optional[str] = Field(default=None, description="Pull request title")
    pr_author: Optional[str] = Field(default=None, description="Pull request author")
    pr_url: Optional[str] = Field(default=None, description="Pull request URL")
    review_author: Optional[str] = Field(default=None, description="Review comment author")


class Outcome(BaseModel):
    """Records the result of applying a piece of knowledge."""

    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    result: OutcomeResult
    context: str = Field(description="Description of how the knowledge was applied")
    delta: float = Field(
        description="Confidence adjustment (-1.0 to 1.0)",
        ge=-1.0,
        le=1.0
    )


class ProjectContext(BaseModel):
    """Context about the project where a learning originated."""

    project_type: Optional[str] = Field(
        default=None,
        description="Type of project (python, node, rust, go, etc.)"
    )
    tech_stack: list[str] = Field(
        default_factory=list,
        description="Technologies/frameworks used (fastapi, react, pytest, etc.)"
    )
    keywords: list[str] = Field(
        default_factory=list,
        description="Keywords extracted from the learning content"
    )


class Learning(BaseModel):
    """A single piece of knowledge extracted from a session."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    category: LearningCategory
    content: str = Field(description="The actual knowledge/insight")
    content_hash: Optional[str] = Field(
        default=None,
        description="Normalized content hash for deduplication (computed automatically)"
    )
    confidence: float = Field(
        default=0.5,
        description="Current confidence level (0.0 to 1.0)",
        ge=0.0,
        le=1.0
    )
    privacy: PrivacyLevel = Field(
        default=PrivacyLevel.PUBLIC,
        description="Privacy level controlling storage and promotion behavior"
    )
    source: Optional[str] = Field(
        default=None,
        description="File path or context where this was learned"
    )
    outcomes: list[Outcome] = Field(
        default_factory=list,
        description=(
            "DEPRECATED: This field exists only for backwards compatibility with "
            "existing block hashes. Actual outcomes are stored in reinforcements.json "
            "to preserve block immutability. This field is always empty after creation; "
            "use Ledger.get_learning_outcomes() to retrieve outcome history."
        )
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Timestamp when this learning was created"
    )
    last_applied: Optional[datetime] = Field(
        default=None,
        description="Timestamp when this learning was last referenced/applied"
    )
    project_context: Optional[ProjectContext] = Field(
        default=None,
        description="Context about the project where this learning originated"
    )
    derived_from: Optional[str] = Field(
        default=None,
        description="ID of the learning this was derived/imported from"
    )

    # Git integration fields
    learning_source: LearningSource = Field(
        default=LearningSource.SESSION,
        description="Source from which this learning was extracted"
    )
    git_metadata: Optional[GitSourceMetadata] = Field(
        default=None,
        description="Git-specific metadata when source is git-related"
    )
    co_authors: list[str] = Field(
        default_factory=list,
        description="Co-authors from Co-Authored-By git trailers"
    )

    def model_post_init(self, __context) -> None:
        """Compute content_hash after model initialization if not provided."""
        if self.content_hash is None:
            object.__setattr__(self, 'content_hash', compute_content_hash(self.content))

    def hash_dict(self) -> dict:
        """Return only the original fields used for block hash computation.

        This ensures backwards compatibility with existing blocks that were
        created before new fields (content_hash, created_at, etc.) were added.
        """
        return {
            "id": self.id,
            "category": self.category.value,
            "content": self.content,
            "confidence": self.confidence,
            "source": self.source,
            "outcomes": [o.model_dump(mode="json") for o in self.outcomes],
        }

    def apply_outcome(self, result: OutcomeResult, context: str) -> None:
        """Record an outcome and adjust confidence based on result.

        DEPRECATED: This method modifies in-memory state only. Changes to
        outcomes and confidence are NOT persisted when the Learning is stored
        in a block (blocks are immutable). Use Ledger.record_outcome() instead,
        which stores outcomes in reinforcements.json.
        """
        delta_map = {
            OutcomeResult.SUCCESS: 0.1,
            OutcomeResult.PARTIAL: 0.02,
            OutcomeResult.FAILURE: -0.15,
        }
        delta = delta_map[result]

        outcome = Outcome(result=result, context=context, delta=delta)
        self.outcomes.append(outcome)

        # Apply confidence adjustment with bounds
        self.confidence = max(0.0, min(1.0, self.confidence + delta))

        # Update last_applied timestamp
        self.last_applied = datetime.now(timezone.utc)


class Block(BaseModel):
    """An immutable block in the ledger chain."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    session_id: str = Field(description="ID of the Claude session that created this block")
    parent_block: Optional[str] = Field(
        default=None,
        description="ID of the previous block in the chain"
    )
    learnings: list[Learning] = Field(
        default_factory=list,
        description="Knowledge extracted in this session"
    )
    author_key_id: Optional[str] = Field(
        default=None,
        description="Key ID of block author for cryptographic signing"
    )
    signature: Optional[str] = Field(
        default=None,
        description="Base64-encoded Ed25519 signature of block hash"
    )

    @computed_field
    @property
    def hash(self) -> str:
        """Compute SHA-256 hash of the block contents.

        Uses only the original fields for backwards compatibility with
        existing blocks created before new Learning fields were added.
        """
        content = {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "parent_block": self.parent_block,
            "learnings": [l.hash_dict() for l in self.learnings],
        }
        content_str = json.dumps(content, sort_keys=True)
        return hashlib.sha256(content_str.encode()).hexdigest()

    def add_learning(
        self,
        category: LearningCategory,
        content: str,
        source: Optional[str] = None,
        confidence: float = 0.5,
    ) -> Learning:
        """Add a new learning to this block."""
        learning = Learning(
            category=category,
            content=content,
            source=source,
            confidence=confidence,
        )
        self.learnings.append(learning)
        return learning
