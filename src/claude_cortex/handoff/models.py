"""Data models for the handoff system."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import re


@dataclass
class Handoff:
    """Represents a work-in-progress state capture for session handoffs."""

    session_id: str
    timestamp: datetime
    completed_tasks: list[str] = field(default_factory=list)
    pending_tasks: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    modified_files: list[str] = field(default_factory=list)
    context_notes: str = ""

    def to_markdown(self) -> str:
        """Serialize the handoff to markdown format with YAML frontmatter."""
        lines = [
            "---",
            f"session_id: {self.session_id}",
            f"timestamp: {self.timestamp.isoformat()}",
            "---",
            "",
        ]

        # Completed tasks
        lines.append("## Completed")
        if self.completed_tasks:
            for task in self.completed_tasks:
                lines.append(f"- {task}")
        else:
            lines.append("- None")
        lines.append("")

        # Pending tasks
        lines.append("## Pending")
        if self.pending_tasks:
            for task in self.pending_tasks:
                lines.append(f"- {task}")
        else:
            lines.append("- None")
        lines.append("")

        # Modified files
        lines.append("## Modified Files")
        if self.modified_files:
            for file_path in self.modified_files:
                lines.append(f"- {file_path}")
        else:
            lines.append("- None")
        lines.append("")

        # Blockers
        lines.append("## Blockers")
        if self.blockers:
            for blocker in self.blockers:
                lines.append(f"- {blocker}")
        else:
            lines.append("- None")
        lines.append("")

        # Context notes
        lines.append("## Context")
        lines.append(self.context_notes if self.context_notes else "No additional context.")
        lines.append("")

        return "\n".join(lines)

    @classmethod
    def from_markdown(cls, content: str) -> Optional["Handoff"]:
        """Parse a handoff from markdown format with YAML frontmatter.

        Args:
            content: The markdown content to parse.

        Returns:
            A Handoff instance if parsing succeeds, None otherwise.
        """
        if not content or not content.strip():
            return None

        try:
            # Parse YAML frontmatter
            frontmatter_match = re.match(
                r"^---\s*\n(.*?)\n---\s*\n",
                content,
                re.DOTALL
            )
            if not frontmatter_match:
                return None

            frontmatter = frontmatter_match.group(1)
            body = content[frontmatter_match.end():]

            # Extract session_id and timestamp from frontmatter
            session_id_match = re.search(r"session_id:\s*(.+)", frontmatter)
            timestamp_match = re.search(r"timestamp:\s*(.+)", frontmatter)

            if not session_id_match or not timestamp_match:
                return None

            session_id = session_id_match.group(1).strip()
            timestamp_str = timestamp_match.group(1).strip()

            # Parse timestamp
            try:
                timestamp = datetime.fromisoformat(timestamp_str)
            except ValueError:
                return None

            # Parse sections from body
            completed_tasks = cls._parse_list_section(body, "Completed")
            pending_tasks = cls._parse_list_section(body, "Pending")
            modified_files = cls._parse_list_section(body, "Modified Files")
            blockers = cls._parse_list_section(body, "Blockers")
            context_notes = cls._parse_context_section(body)

            return cls(
                session_id=session_id,
                timestamp=timestamp,
                completed_tasks=completed_tasks,
                pending_tasks=pending_tasks,
                blockers=blockers,
                modified_files=modified_files,
                context_notes=context_notes,
            )

        except Exception:
            return None

    @staticmethod
    def _parse_list_section(body: str, section_name: str) -> list[str]:
        """Parse a bulleted list section from markdown body.

        Args:
            body: The markdown body to parse.
            section_name: The section header name (without ##).

        Returns:
            List of items from the section.
        """
        # Find the section
        pattern = rf"##\s*{re.escape(section_name)}\s*\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
        if not match:
            return []

        section_content = match.group(1)

        # Parse list items
        items = []
        for line in section_content.strip().split("\n"):
            line = line.strip()
            if line.startswith("- "):
                item = line[2:].strip()
                # Skip "None" placeholder
                if item.lower() != "none":
                    items.append(item)

        return items

    @staticmethod
    def _parse_context_section(body: str) -> str:
        """Parse the Context section from markdown body.

        Args:
            body: The markdown body to parse.

        Returns:
            The context notes as a string.
        """
        pattern = r"##\s*Context\s*\n(.*?)(?=\n##|\Z)"
        match = re.search(pattern, body, re.DOTALL | re.IGNORECASE)
        if not match:
            return ""

        context = match.group(1).strip()

        # Return empty string if it's the default placeholder
        if context.lower() == "no additional context.":
            return ""

        return context
