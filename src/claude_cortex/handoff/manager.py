"""Manager for handoff creation and retrieval."""

import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Handoff


class HandoffManager:
    """Manages handoff creation, storage, and retrieval."""

    def __init__(self, project_path: Optional[Path] = None):
        """Initialize the handoff manager.

        Args:
            project_path: Path to the project directory. Defaults to cwd.
        """
        self.project_path = project_path or Path.cwd()
        self.handoffs_dir = self.project_path / ".claude" / "handoffs"

    def _ensure_handoffs_dir(self, session_id: str) -> Path:
        """Ensure the handoffs directory exists for a session.

        Args:
            session_id: The session identifier.

        Returns:
            Path to the session's handoffs directory.
        """
        session_dir = self.handoffs_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def _get_modified_files(self) -> list[str]:
        """Get list of modified files using git.

        Returns:
            List of file paths that have been modified.
        """
        try:
            # Get staged and unstaged changes
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                return []

            files = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    # Format is "XY filename" where X is staged status, Y is unstaged
                    # Skip the status codes (first 3 characters)
                    file_path = line[3:].strip()
                    # Handle renamed files (format: "old -> new")
                    if " -> " in file_path:
                        file_path = file_path.split(" -> ")[1]
                    files.append(file_path)
            return files
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            return []

    def _extract_tasks_from_transcript(
        self,
        transcript_path: Optional[str] = None,
    ) -> tuple[list[str], list[str]]:
        """Extract completed and pending tasks from transcript.

        This is a simplified extraction - actual implementation would
        parse the transcript JSON to identify task patterns.

        Args:
            transcript_path: Path to the session transcript file.

        Returns:
            Tuple of (completed_tasks, pending_tasks).
        """
        # Placeholder - actual implementation would parse transcript
        # For now, return empty lists that can be populated by caller
        return [], []

    def create_handoff(
        self,
        session_id: str,
        completed_tasks: Optional[list[str]] = None,
        pending_tasks: Optional[list[str]] = None,
        blockers: Optional[list[str]] = None,
        context_notes: str = "",
        transcript_path: Optional[str] = None,
    ) -> Handoff:
        """Create a new handoff capturing current work-in-progress state.

        Args:
            session_id: The session identifier.
            completed_tasks: List of completed tasks.
            pending_tasks: List of pending tasks.
            blockers: List of blockers.
            context_notes: Additional context notes.
            transcript_path: Optional path to transcript for task extraction.

        Returns:
            The created Handoff instance.
        """
        # Get modified files from git
        modified_files = self._get_modified_files()

        # Try to extract tasks from transcript if provided
        if transcript_path and (completed_tasks is None or pending_tasks is None):
            extracted_completed, extracted_pending = self._extract_tasks_from_transcript(
                transcript_path
            )
            if completed_tasks is None:
                completed_tasks = extracted_completed
            if pending_tasks is None:
                pending_tasks = extracted_pending

        handoff = Handoff(
            session_id=session_id,
            timestamp=datetime.now(timezone.utc),
            completed_tasks=completed_tasks or [],
            pending_tasks=pending_tasks or [],
            blockers=blockers or [],
            modified_files=modified_files,
            context_notes=context_notes,
        )

        return handoff

    def save_handoff(self, handoff: Handoff) -> Path:
        """Save a handoff to disk.

        Args:
            handoff: The handoff to save.

        Returns:
            Path to the saved handoff file.
        """
        session_dir = self._ensure_handoffs_dir(handoff.session_id)

        # Create filename with timestamp (includes microseconds to prevent race conditions)
        timestamp_str = handoff.timestamp.strftime("%Y%m%d-%H%M%S-%f")
        filename = f"handoff-{timestamp_str}.md"
        file_path = session_dir / filename

        # Write handoff as markdown
        content = handoff.to_markdown()
        file_path.write_text(content, encoding="utf-8")

        return file_path

    def load_latest_handoff(self, session_id: Optional[str] = None) -> Optional[Handoff]:
        """Load the most recent handoff.

        Args:
            session_id: Optional session ID to filter by.
                       If not provided, returns latest across all sessions.

        Returns:
            The most recent Handoff, or None if not found.
        """
        if not self.handoffs_dir.exists():
            return None

        handoff_files: list[Path] = []

        if session_id:
            # Look in specific session directory
            session_dir = self.handoffs_dir / session_id
            if session_dir.exists():
                handoff_files = list(session_dir.glob("handoff-*.md"))
        else:
            # Look across all session directories
            handoff_files = list(self.handoffs_dir.glob("*/handoff-*.md"))

        if not handoff_files:
            return None

        # Sort by filename (which contains timestamp) to get latest
        handoff_files.sort(key=lambda p: p.name, reverse=True)

        # Try to load the most recent one
        for handoff_file in handoff_files:
            try:
                content = handoff_file.read_text(encoding="utf-8")
                handoff = Handoff.from_markdown(content)
                if handoff:
                    return handoff
            except Exception:
                continue

        return None

    def list_handoffs(
        self,
        session_id: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict]:
        """List available handoffs.

        Args:
            session_id: Optional session ID to filter by.
            limit: Maximum number of handoffs to return.

        Returns:
            List of handoff metadata dictionaries.
        """
        if not self.handoffs_dir.exists():
            return []

        handoff_files: list[Path] = []

        if session_id:
            session_dir = self.handoffs_dir / session_id
            if session_dir.exists():
                handoff_files = list(session_dir.glob("handoff-*.md"))
        else:
            handoff_files = list(self.handoffs_dir.glob("*/handoff-*.md"))

        if not handoff_files:
            return []

        # Sort by filename (which contains timestamp) to get most recent first
        handoff_files.sort(key=lambda p: p.name, reverse=True)

        results = []
        for handoff_file in handoff_files[:limit]:
            try:
                content = handoff_file.read_text(encoding="utf-8")
                handoff = Handoff.from_markdown(content)
                if handoff:
                    results.append({
                        "session_id": handoff.session_id,
                        "timestamp": handoff.timestamp.isoformat(),
                        "file_path": str(handoff_file),
                        "completed_count": len(handoff.completed_tasks),
                        "pending_count": len(handoff.pending_tasks),
                        "blocker_count": len(handoff.blockers),
                        "modified_files_count": len(handoff.modified_files),
                    })
            except Exception:
                continue

        return results

    def get_handoff_context(self, handoff: Handoff) -> str:
        """Generate context string from a handoff for session injection.

        Args:
            handoff: The handoff to generate context from.

        Returns:
            Formatted context string for session start.
        """
        lines = ["## Previous Session Handoff"]
        lines.append(f"Session: {handoff.session_id}")
        lines.append(f"Timestamp: {handoff.timestamp.isoformat()}")
        lines.append("")

        if handoff.completed_tasks:
            lines.append("### Completed")
            for task in handoff.completed_tasks:
                lines.append(f"- {task}")
            lines.append("")

        if handoff.pending_tasks:
            lines.append("### Pending Tasks (continue from here)")
            for task in handoff.pending_tasks:
                lines.append(f"- {task}")
            lines.append("")

        if handoff.blockers:
            lines.append("### Blockers to Address")
            for blocker in handoff.blockers:
                lines.append(f"- {blocker}")
            lines.append("")

        if handoff.modified_files:
            lines.append("### Recently Modified Files")
            for file_path in handoff.modified_files[:10]:  # Limit to 10
                lines.append(f"- {file_path}")
            lines.append("")

        if handoff.context_notes:
            lines.append("### Context Notes")
            lines.append(handoff.context_notes)
            lines.append("")

        return "\n".join(lines)
