"""Data models for the summary system."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class Summary(BaseModel):
    """Represents a transcript summary captured before compaction."""

    session_id: str = Field(description="ID of the Claude session")
    timestamp: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the summary was captured"
    )
    summary_text: str = Field(
        description="The compaction summary text"
    )
    key_decisions: list[str] = Field(
        default_factory=list,
        description="Decisions made during the session"
    )
    files_discussed: list[str] = Field(
        default_factory=list,
        description="Files that were read or modified"
    )
    learning_ids: list[str] = Field(
        default_factory=list,
        description="IDs of learnings captured in this session"
    )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict) -> "Summary":
        """Create a Summary from a dictionary."""
        return cls.model_validate(data)

    def format_for_context(self) -> str:
        """Format summary for session context injection.

        Returns:
            Formatted string suitable for injecting into a new session.
        """
        lines = [f"### Session {self.session_id[:8]}"]
        lines.append(f"*{self.timestamp.strftime('%Y-%m-%d %H:%M')}*")
        lines.append("")

        if self.summary_text:
            lines.append(self.summary_text)
            lines.append("")

        if self.key_decisions:
            lines.append("**Key Decisions:**")
            for decision in self.key_decisions[:5]:
                lines.append(f"- {decision}")
            lines.append("")

        if self.files_discussed:
            lines.append("**Files Involved:**")
            for file_path in self.files_discussed[:10]:
                lines.append(f"- {file_path}")
            lines.append("")

        return "\n".join(lines)
