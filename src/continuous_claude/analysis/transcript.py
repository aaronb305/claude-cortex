"""LLM-powered transcript analysis.

Provides Braintrust-like learning extraction by analyzing full transcripts
with Claude, extracting structured insights without requiring explicit tags.
"""

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .metrics import SessionMetrics, extract_metrics_from_transcript


@dataclass
class SessionInsights:
    """Structured insights extracted from a session.

    Similar to Braintrust's learning extraction:
    - What Worked: Successful approaches and decisions
    - What Failed: Errors, dead ends, incorrect assumptions
    - Patterns: Reusable solutions and workflows
    - Key Decisions: Important choices made during the session
    """

    session_id: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Core insights (Braintrust-style)
    what_worked: list[str] = field(default_factory=list)
    what_failed: list[str] = field(default_factory=list)
    patterns: list[str] = field(default_factory=list)
    key_decisions: list[str] = field(default_factory=list)

    # Additional context
    tools_used: list[str] = field(default_factory=list)
    files_modified: list[str] = field(default_factory=list)
    summary: str = ""

    # Metrics
    metrics: Optional[SessionMetrics] = None

    def to_learnings(self) -> list[dict]:
        """Convert insights to learning format for ledger storage.

        Returns:
            List of learning dicts ready for ledger ingestion
        """
        learnings = []

        # What worked → patterns/discoveries
        for item in self.what_worked:
            if len(item) > 20:  # Filter short/trivial items
                learnings.append({
                    "category": "pattern",
                    "content": item,
                    "confidence": 0.7,  # Higher confidence for successful approaches
                    "source": f"session-analysis:{self.session_id}",
                })

        # What failed → errors
        for item in self.what_failed:
            if len(item) > 20:
                learnings.append({
                    "category": "error",
                    "content": item,
                    "confidence": 0.6,
                    "source": f"session-analysis:{self.session_id}",
                })

        # Patterns → patterns
        for item in self.patterns:
            if len(item) > 20:
                learnings.append({
                    "category": "pattern",
                    "content": item,
                    "confidence": 0.65,
                    "source": f"session-analysis:{self.session_id}",
                })

        # Key decisions → decisions
        for item in self.key_decisions:
            if len(item) > 20:
                learnings.append({
                    "category": "decision",
                    "content": item,
                    "confidence": 0.6,
                    "source": f"session-analysis:{self.session_id}",
                })

        return learnings

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp.isoformat(),
            "what_worked": self.what_worked,
            "what_failed": self.what_failed,
            "patterns": self.patterns,
            "key_decisions": self.key_decisions,
            "tools_used": self.tools_used,
            "files_modified": self.files_modified,
            "summary": self.summary,
            "metrics": self.metrics.to_dict() if self.metrics else None,
        }

    def to_markdown(self) -> str:
        """Convert to markdown format for human reading."""
        lines = [
            f"# Session Analysis: {self.session_id}",
            f"*Generated: {self.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}*",
            "",
        ]

        if self.summary:
            lines.extend(["## Summary", self.summary, ""])

        if self.what_worked:
            lines.append("## What Worked")
            for item in self.what_worked:
                lines.append(f"- {item}")
            lines.append("")

        if self.what_failed:
            lines.append("## What Failed")
            for item in self.what_failed:
                lines.append(f"- {item}")
            lines.append("")

        if self.patterns:
            lines.append("## Patterns Identified")
            for item in self.patterns:
                lines.append(f"- {item}")
            lines.append("")

        if self.key_decisions:
            lines.append("## Key Decisions")
            for item in self.key_decisions:
                lines.append(f"- {item}")
            lines.append("")

        if self.tools_used:
            lines.append("## Tools Used")
            lines.append(", ".join(self.tools_used))
            lines.append("")

        if self.metrics:
            lines.append("## Metrics")
            lines.append(f"- Duration: {self.metrics.duration_seconds:.1f}s")
            lines.append(f"- Turns: {self.metrics.turn_count}")
            lines.append(f"- Tool calls: {self.metrics.tool_call_count}")
            lines.append(f"- Success rate: {self.metrics.overall_success_rate:.1f}%")

            if self.metrics.get_frequent_patterns():
                lines.append("")
                lines.append("### Frequent Patterns")
                for pattern, count in self.metrics.get_frequent_patterns()[:5]:
                    lines.append(f"- {pattern} ({count}x)")

        return "\n".join(lines)


# Analysis prompt for Claude
ANALYSIS_PROMPT = '''Analyze this Claude Code session transcript and extract structured insights.

<transcript>
{transcript}
</transcript>

Extract the following in JSON format:
{{
  "summary": "2-3 sentence summary of what was accomplished",
  "what_worked": [
    "Specific approaches, techniques, or decisions that led to success",
    "Include context about why they worked"
  ],
  "what_failed": [
    "Errors encountered, dead ends, incorrect assumptions",
    "Include what was tried and why it failed"
  ],
  "patterns": [
    "Reusable solutions or workflows discovered",
    "Generalizable techniques that could apply elsewhere"
  ],
  "key_decisions": [
    "Important architectural or implementation choices made",
    "Include rationale if apparent"
  ],
  "files_modified": ["list", "of", "files"]
}}

Focus on actionable insights that would help in future sessions. Be specific and include enough context to understand the insight without the full transcript.'''


class TranscriptAnalyzer:
    """Analyzes session transcripts to extract insights.

    Uses Claude for intelligent extraction instead of simple regex matching.
    Falls back to regex-based extraction if LLM analysis is unavailable.
    """

    def __init__(self, use_llm: bool = True, model: str = "claude-sonnet-4-20250514"):
        """Initialize the analyzer.

        Args:
            use_llm: Whether to use LLM for analysis (vs regex fallback)
            model: Claude model to use for analysis
        """
        self.use_llm = use_llm
        self.model = model

    def analyze(
        self,
        transcript_text: str,
        session_id: str,
        events: Optional[list[dict]] = None,
    ) -> SessionInsights:
        """Analyze a transcript and extract insights.

        Args:
            transcript_text: The full transcript text
            session_id: Session identifier
            events: Optional parsed transcript events for metrics

        Returns:
            SessionInsights with extracted data
        """
        insights = SessionInsights(session_id=session_id)

        # Extract metrics if events provided
        if events:
            insights.metrics = extract_metrics_from_transcript(events, session_id)
            insights.tools_used = list(insights.metrics.tool_metrics.keys())

        # Try LLM analysis first
        if self.use_llm:
            try:
                llm_insights = self._analyze_with_llm(transcript_text)
                if llm_insights:
                    insights.summary = llm_insights.get("summary", "")
                    insights.what_worked = llm_insights.get("what_worked", [])
                    insights.what_failed = llm_insights.get("what_failed", [])
                    insights.patterns = llm_insights.get("patterns", [])
                    insights.key_decisions = llm_insights.get("key_decisions", [])
                    insights.files_modified = llm_insights.get("files_modified", [])
                    return insights
            except Exception as e:
                # Fall through to regex fallback
                pass

        # Regex fallback
        insights = self._analyze_with_regex(transcript_text, insights)
        return insights

    def _analyze_with_llm(self, transcript_text: str) -> Optional[dict]:
        """Use Claude to analyze the transcript.

        Args:
            transcript_text: Full transcript text

        Returns:
            Parsed JSON response or None if failed
        """
        # Truncate very long transcripts
        max_chars = 50000
        if len(transcript_text) > max_chars:
            # Keep beginning and end
            half = max_chars // 2
            transcript_text = (
                transcript_text[:half]
                + "\n\n[... transcript truncated ...]\n\n"
                + transcript_text[-half:]
            )

        prompt = ANALYSIS_PROMPT.format(transcript=transcript_text)

        try:
            # Use claude CLI for analysis
            result = subprocess.run(
                [
                    "claude",
                    "-p", prompt,
                    "--model", self.model,
                    "--output-format", "json",
                ],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                return None

            # Parse the response
            response = json.loads(result.stdout)

            # Handle different response formats
            if isinstance(response, dict):
                # Direct JSON response
                if "result" in response:
                    # Wrapped response
                    content = response["result"]
                    if isinstance(content, str):
                        # Need to parse JSON from string
                        return self._extract_json_from_text(content)
                    return content
                elif "what_worked" in response:
                    return response

            return None

        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            return None

    def _extract_json_from_text(self, text: str) -> Optional[dict]:
        """Extract JSON object from text that may contain other content."""
        # Try to find JSON block
        json_match = re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        return None

    def _analyze_with_regex(
        self,
        transcript_text: str,
        insights: SessionInsights,
    ) -> SessionInsights:
        """Fallback regex-based analysis.

        Args:
            transcript_text: Full transcript text
            insights: Partially filled insights to complete

        Returns:
            Updated insights
        """
        # Extract tagged content (existing approach)
        tag_patterns = {
            "what_worked": r'\[(?:SUCCESS|WORKED|PATTERN)\]\s*(.+?)(?:\n|$)',
            "what_failed": r'\[(?:ERROR|FAILED|ISSUE)\]\s*(.+?)(?:\n|$)',
            "patterns": r'\[PATTERN\]\s*(.+?)(?:\n|$)',
            "key_decisions": r'\[DECISION\]\s*(.+?)(?:\n|$)',
        }

        for field, pattern in tag_patterns.items():
            matches = re.findall(pattern, transcript_text, re.IGNORECASE)
            current = getattr(insights, field)
            current.extend([m.strip() for m in matches if len(m.strip()) > 10])

        # Extract file modifications
        file_patterns = [
            r'(?:wrote|created|modified|updated|edited)\s+[`"\']?([a-zA-Z0-9_\-./]+\.[a-zA-Z0-9]+)[`"\']?',
            r'Write tool.*?file_path["\']:\s*["\']([^"\']+)["\']',
            r'Edit tool.*?file_path["\']:\s*["\']([^"\']+)["\']',
        ]

        for pattern in file_patterns:
            matches = re.findall(pattern, transcript_text, re.IGNORECASE)
            insights.files_modified.extend(matches)

        insights.files_modified = list(set(insights.files_modified))

        # Generate basic summary
        if not insights.summary:
            # Count some basics
            tool_count = len(insights.tools_used) if insights.tools_used else 0
            file_count = len(insights.files_modified)
            insights.summary = f"Session with {tool_count} tools used, {file_count} files modified."

        return insights

    def analyze_from_file(self, transcript_path: Path, session_id: str) -> SessionInsights:
        """Analyze a transcript from a file.

        Args:
            transcript_path: Path to transcript file (JSON or text)
            session_id: Session identifier

        Returns:
            SessionInsights with extracted data
        """
        events = None
        transcript_text = ""

        try:
            with open(transcript_path) as f:
                content = f.read()

            # Try to parse as JSON (JSONL format)
            lines = content.strip().split('\n')
            events = []
            for line in lines:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

            # Extract text from events
            for event in events:
                if event.get("type") == "assistant":
                    message = event.get("message", {})
                    if isinstance(message, dict):
                        content_list = message.get("content", [])
                        for item in content_list:
                            if isinstance(item, dict) and item.get("type") == "text":
                                transcript_text += item.get("text", "") + "\n"
                    elif isinstance(message, str):
                        transcript_text += message + "\n"

        except Exception:
            # Fallback: treat as plain text
            transcript_text = content if 'content' in dir() else ""

        return self.analyze(transcript_text, session_id, events)


def save_insights(insights: SessionInsights, output_dir: Path) -> Path:
    """Save insights to disk.

    Args:
        insights: The insights to save
        output_dir: Directory to save to

    Returns:
        Path to saved file
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = insights.timestamp.strftime("%Y%m%d-%H%M%S")
    filename = f"insights-{timestamp}.json"
    filepath = output_dir / filename

    with open(filepath, "w") as f:
        json.dump(insights.to_dict(), f, indent=2)

    # Also save markdown version for human reading
    md_path = output_dir / f"insights-{timestamp}.md"
    with open(md_path, "w") as f:
        f.write(insights.to_markdown())

    return filepath
