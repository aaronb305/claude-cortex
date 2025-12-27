"""Data models for the ledger system."""

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Optional
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field


class LearningCategory(str, Enum):
    """Categories of knowledge that can be learned."""

    DISCOVERY = "discovery"  # New information about codebase, APIs, patterns
    DECISION = "decision"    # Architectural choices, tradeoffs, rationale
    ERROR = "error"          # Mistakes to avoid, failed approaches, gotchas
    PATTERN = "pattern"      # Reusable solutions, templates, conventions


class OutcomeResult(str, Enum):
    """Result of applying knowledge."""

    SUCCESS = "success"
    FAILURE = "failure"
    PARTIAL = "partial"


class Outcome(BaseModel):
    """Records the result of applying a piece of knowledge."""

    timestamp: datetime = Field(default_factory=datetime.utcnow)
    result: OutcomeResult
    context: str = Field(description="Description of how the knowledge was applied")
    delta: float = Field(
        description="Confidence adjustment (-1.0 to 1.0)",
        ge=-1.0,
        le=1.0
    )


class Learning(BaseModel):
    """A single piece of knowledge extracted from a session."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    category: LearningCategory
    content: str = Field(description="The actual knowledge/insight")
    confidence: float = Field(
        default=0.5,
        description="Current confidence level (0.0 to 1.0)",
        ge=0.0,
        le=1.0
    )
    source: Optional[str] = Field(
        default=None,
        description="File path or context where this was learned"
    )
    outcomes: list[Outcome] = Field(
        default_factory=list,
        description="History of applications and their results"
    )

    def apply_outcome(self, result: OutcomeResult, context: str) -> None:
        """Record an outcome and adjust confidence based on result."""
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


class Block(BaseModel):
    """An immutable block in the ledger chain."""

    id: str = Field(default_factory=lambda: str(uuid4())[:8])
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    session_id: str = Field(description="ID of the Claude session that created this block")
    parent_block: Optional[str] = Field(
        default=None,
        description="ID of the previous block in the chain"
    )
    learnings: list[Learning] = Field(
        default_factory=list,
        description="Knowledge extracted in this session"
    )

    @computed_field
    @property
    def hash(self) -> str:
        """Compute SHA-256 hash of the block contents."""
        content = {
            "id": self.id,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "parent_block": self.parent_block,
            "learnings": [l.model_dump(mode="json") for l in self.learnings],
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
