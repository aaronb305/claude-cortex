"""Manager for summary creation, storage, and retrieval."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import Summary


class SummaryManager:
    """Manages summary creation, storage, and retrieval."""

    def __init__(self, project_path: Optional[Path] = None):
        """Initialize the summary manager.

        Args:
            project_path: Path to the project directory. Defaults to cwd.
        """
        self.project_path = project_path or Path.cwd()
        self.summaries_dir = self.project_path / ".claude" / "summaries"

    def _ensure_summaries_dir(self, session_id: str) -> Path:
        """Ensure the summaries directory exists for a session.

        Args:
            session_id: The session identifier.

        Returns:
            Path to the session's summaries directory.
        """
        session_dir = self.summaries_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        return session_dir

    def _read_json(self, path: Path) -> Optional[dict]:
        """Read JSON from a file.

        Args:
            path: Path to the JSON file.

        Returns:
            Parsed JSON data or None if file doesn't exist or is invalid.
        """
        try:
            with open(path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def _write_json(self, path: Path, data: dict) -> None:
        """Write JSON to a file.

        Args:
            path: Path to the JSON file.
            data: Data to write.
        """
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def extract_decisions_from_text(self, text: str) -> list[str]:
        """Extract key decisions from transcript text.

        Args:
            text: The assistant messages text.

        Returns:
            List of decisions identified.
        """
        decisions = []
        seen = set()

        # Pattern to find decision-related statements
        patterns = [
            r"(?:I(?:'ve| have)?\s+)?decided to\s+(.+?)(?:\.|$)",
            r"(?:I(?:'ll| will)?\s+)?(?:chose|choose) to\s+(.+?)(?:\.|$)",
            r"\[DECISION\]\s*(.+?)(?:\.|$|\n|\[)",
            r"(?:The|My)\s+approach (?:is|will be) to\s+(.+?)(?:\.|$)",
            r"(?:I(?:'m| am)?\s+)?going with\s+(.+?)(?:\.|$)",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE | re.MULTILINE)
            for match in matches:
                decision = match.strip()
                decision = re.sub(r"\s+", " ", decision)[:200]
                if decision and len(decision) > 15 and decision.lower() not in seen:
                    seen.add(decision.lower())
                    decisions.append(decision)

        return decisions[:10]

    def extract_files_from_text(self, text: str) -> list[str]:
        """Extract file paths discussed in the transcript.

        Args:
            text: The assistant messages text.

        Returns:
            List of file paths mentioned.
        """
        files = set()

        # Common file patterns
        patterns = [
            r"(?:reading|read|wrote|writing|created|modified|updated|editing|edited)\s+[`\"']?([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)[`\"']?",
            r"(?:in|from|at|see|file)\s+[`\"']?([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)[`\"']?",
            r"[`\"']([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]{1,5})[`\"']",
        ]

        for pattern in patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                file_path = match.strip()
                # Filter out common false positives
                if (
                    file_path
                    and len(file_path) > 3
                    and not file_path.startswith("http")
                    and "/" not in file_path[:2]  # Avoid //
                    and not file_path.endswith(".0")  # Avoid version numbers
                ):
                    files.add(file_path)

        return sorted(list(files))[:30]

    def create_summary(
        self,
        session_id: str,
        summary_text: str,
        assistant_text: str = "",
        learning_ids: Optional[list[str]] = None,
        files_discussed: Optional[list[str]] = None,
        key_decisions: Optional[list[str]] = None,
    ) -> Summary:
        """Create a new summary from compaction context.

        Args:
            session_id: The session identifier.
            summary_text: The compaction summary text.
            assistant_text: Full assistant messages for extraction.
            learning_ids: List of learning IDs captured in this session.
            files_discussed: Explicit list of files. If None, extracted from text.
            key_decisions: Explicit list of decisions. If None, extracted from text.

        Returns:
            The created Summary instance.
        """
        # Extract decisions if not provided
        if key_decisions is None and assistant_text:
            key_decisions = self.extract_decisions_from_text(assistant_text)

        # Extract files if not provided
        if files_discussed is None and assistant_text:
            files_discussed = self.extract_files_from_text(assistant_text)

        return Summary(
            session_id=session_id,
            timestamp=datetime.now(timezone.utc),
            summary_text=summary_text,
            key_decisions=key_decisions or [],
            files_discussed=files_discussed or [],
            learning_ids=learning_ids or [],
        )

    def save_summary(self, summary: Summary) -> Path:
        """Save a summary to disk.

        Args:
            summary: The summary to save.

        Returns:
            Path to the saved summary file.
        """
        session_dir = self._ensure_summaries_dir(summary.session_id)

        # Create filename with timestamp
        timestamp_str = summary.timestamp.strftime("%Y%m%d-%H%M%S")
        filename = f"summary-{timestamp_str}.json"
        file_path = session_dir / filename

        # Write summary as JSON
        self._write_json(file_path, summary.to_dict())

        return file_path

    def load_summary(self, file_path: Path) -> Optional[Summary]:
        """Load a summary from a file.

        Args:
            file_path: Path to the summary file.

        Returns:
            The Summary instance or None if loading fails.
        """
        data = self._read_json(file_path)
        if data:
            try:
                return Summary.from_dict(data)
            except Exception:
                return None
        return None

    def load_latest_summary(self, session_id: Optional[str] = None) -> Optional[Summary]:
        """Load the most recent summary.

        Args:
            session_id: Optional session ID to filter by.
                       If not provided, returns latest across all sessions.

        Returns:
            The most recent Summary, or None if not found.
        """
        if not self.summaries_dir.exists():
            return None

        summary_files: list[Path] = []

        if session_id:
            # Look in specific session directory
            session_dir = self.summaries_dir / session_id
            if session_dir.exists():
                summary_files = list(session_dir.glob("summary-*.json"))
        else:
            # Look across all session directories
            summary_files = list(self.summaries_dir.glob("*/summary-*.json"))

        if not summary_files:
            return None

        # Sort by filename (which contains timestamp) to get latest
        summary_files.sort(key=lambda p: p.name, reverse=True)

        # Try to load the most recent one
        for summary_file in summary_files:
            summary = self.load_summary(summary_file)
            if summary:
                return summary

        return None

    def load_recent_summaries(
        self,
        limit: int = 5,
        session_id: Optional[str] = None,
    ) -> list[Summary]:
        """Load recent summaries.

        Args:
            limit: Maximum number of summaries to return.
            session_id: Optional session ID to filter by.

        Returns:
            List of recent summaries, newest first.
        """
        if not self.summaries_dir.exists():
            return []

        summary_files: list[Path] = []

        if session_id:
            session_dir = self.summaries_dir / session_id
            if session_dir.exists():
                summary_files = list(session_dir.glob("summary-*.json"))
        else:
            summary_files = list(self.summaries_dir.glob("*/summary-*.json"))

        if not summary_files:
            return []

        # Sort by filename (which contains timestamp) to get most recent first
        summary_files.sort(key=lambda p: p.name, reverse=True)

        results = []
        for summary_file in summary_files:
            if len(results) >= limit:
                break
            summary = self.load_summary(summary_file)
            if summary:
                results.append(summary)

        return results

    def list_summaries(
        self,
        session_id: Optional[str] = None,
        limit: int = 20,
    ) -> list[dict]:
        """List available summaries.

        Args:
            session_id: Optional session ID to filter by.
            limit: Maximum number of summaries to return.

        Returns:
            List of summary metadata dictionaries.
        """
        if not self.summaries_dir.exists():
            return []

        summary_files: list[Path] = []

        if session_id:
            session_dir = self.summaries_dir / session_id
            if session_dir.exists():
                summary_files = list(session_dir.glob("summary-*.json"))
        else:
            summary_files = list(self.summaries_dir.glob("*/summary-*.json"))

        if not summary_files:
            return []

        # Sort by filename (which contains timestamp) to get most recent first
        summary_files.sort(key=lambda p: p.name, reverse=True)

        results = []
        for summary_file in summary_files[:limit]:
            summary = self.load_summary(summary_file)
            if summary:
                results.append({
                    "session_id": summary.session_id,
                    "timestamp": summary.timestamp.isoformat(),
                    "file_path": str(summary_file),
                    "decisions_count": len(summary.key_decisions),
                    "files_count": len(summary.files_discussed),
                    "learnings_count": len(summary.learning_ids),
                    "summary_preview": summary.summary_text[:100] + "..."
                    if len(summary.summary_text) > 100
                    else summary.summary_text,
                })

        return results

    def get_context_for_session(self, limit: int = 3) -> str:
        """Generate context string from recent summaries for session injection.

        Args:
            limit: Maximum number of summaries to include.

        Returns:
            Formatted context string for session start.
        """
        summaries = self.load_recent_summaries(limit=limit)
        if not summaries:
            return ""

        lines = ["## Recent Session Summaries"]
        lines.append("")

        for summary in summaries:
            lines.append(summary.format_for_context())

        return "\n".join(lines)
