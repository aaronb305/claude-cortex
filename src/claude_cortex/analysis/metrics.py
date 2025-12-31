"""Session and tool metrics tracking.

Provides analytics on tool usage patterns, success/failure rates,
and session-level metrics similar to Braintrust's observability features.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import json
import re


@dataclass
class ToolCall:
    """A single tool invocation."""

    name: str
    timestamp: datetime
    duration_ms: Optional[float] = None
    success: bool = True
    error: Optional[str] = None
    input_summary: Optional[str] = None
    output_summary: Optional[str] = None


@dataclass
class ToolMetrics:
    """Aggregated metrics for a specific tool."""

    name: str
    call_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_duration_ms: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        """Calculate success rate as percentage."""
        if self.call_count == 0:
            return 100.0
        return (self.success_count / self.call_count) * 100

    @property
    def avg_duration_ms(self) -> float:
        """Calculate average duration in milliseconds."""
        if self.call_count == 0:
            return 0.0
        return self.total_duration_ms / self.call_count

    def record_call(self, success: bool, duration_ms: float = 0, error: Optional[str] = None):
        """Record a tool call."""
        self.call_count += 1
        self.total_duration_ms += duration_ms
        if success:
            self.success_count += 1
        else:
            self.failure_count += 1
            if error:
                self.errors.append(error)


@dataclass
class SessionMetrics:
    """Aggregated metrics for a session."""

    session_id: str
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None

    # Counts
    turn_count: int = 0
    tool_call_count: int = 0
    error_count: int = 0

    # Tool-specific metrics
    tool_metrics: dict[str, ToolMetrics] = field(default_factory=dict)

    # Tool call sequence (for pattern analysis)
    tool_sequence: list[str] = field(default_factory=list)

    # Errors encountered
    errors: list[dict] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        """Calculate session duration in seconds."""
        if self.end_time is None:
            return 0.0
        return (self.end_time - self.start_time).total_seconds()

    @property
    def overall_success_rate(self) -> float:
        """Calculate overall tool success rate."""
        if self.tool_call_count == 0:
            return 100.0
        return ((self.tool_call_count - self.error_count) / self.tool_call_count) * 100

    def record_tool_call(
        self,
        tool_name: str,
        success: bool = True,
        duration_ms: float = 0,
        error: Optional[str] = None,
    ):
        """Record a tool call."""
        self.tool_call_count += 1
        self.tool_sequence.append(tool_name)

        if tool_name not in self.tool_metrics:
            self.tool_metrics[tool_name] = ToolMetrics(name=tool_name)

        self.tool_metrics[tool_name].record_call(success, duration_ms, error)

        if not success:
            self.error_count += 1
            self.errors.append({
                "tool": tool_name,
                "error": error,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

    def record_turn(self):
        """Record a user turn."""
        self.turn_count += 1

    def finalize(self):
        """Mark session as complete."""
        self.end_time = datetime.now(timezone.utc)

    def get_frequent_patterns(self, min_count: int = 2) -> list[tuple[str, int]]:
        """Find frequently occurring tool sequences (2-3 tools)."""
        patterns = {}

        # Look for 2-tool patterns
        for i in range(len(self.tool_sequence) - 1):
            pattern = f"{self.tool_sequence[i]} → {self.tool_sequence[i+1]}"
            patterns[pattern] = patterns.get(pattern, 0) + 1

        # Look for 3-tool patterns
        for i in range(len(self.tool_sequence) - 2):
            pattern = f"{self.tool_sequence[i]} → {self.tool_sequence[i+1]} → {self.tool_sequence[i+2]}"
            patterns[pattern] = patterns.get(pattern, 0) + 1

        # Filter and sort by frequency
        frequent = [(p, c) for p, c in patterns.items() if c >= min_count]
        return sorted(frequent, key=lambda x: x[1], reverse=True)

    def get_failure_patterns(self) -> list[str]:
        """Identify tools that frequently fail together or in sequence."""
        failure_patterns = []

        for i, tool in enumerate(self.tool_sequence):
            if tool in self.tool_metrics and self.tool_metrics[tool].failure_count > 0:
                # Check what came before failed tool
                if i > 0:
                    prev_tool = self.tool_sequence[i-1]
                    pattern = f"{prev_tool} followed by {tool} (failed)"
                    if pattern not in failure_patterns:
                        failure_patterns.append(pattern)

        return failure_patterns

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "session_id": self.session_id,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_seconds": self.duration_seconds,
            "turn_count": self.turn_count,
            "tool_call_count": self.tool_call_count,
            "error_count": self.error_count,
            "overall_success_rate": self.overall_success_rate,
            "tool_metrics": {
                name: {
                    "call_count": m.call_count,
                    "success_rate": m.success_rate,
                    "avg_duration_ms": m.avg_duration_ms,
                    "errors": m.errors[:5],  # Limit errors
                }
                for name, m in self.tool_metrics.items()
            },
            "frequent_patterns": self.get_frequent_patterns(),
            "failure_patterns": self.get_failure_patterns(),
        }


def extract_metrics_from_transcript(events: list[dict], session_id: str) -> SessionMetrics:
    """Extract metrics from a transcript event list.

    Args:
        events: List of transcript events
        session_id: Session identifier

    Returns:
        SessionMetrics with extracted data
    """
    metrics = SessionMetrics(session_id=session_id)

    for event in events:
        event_type = event.get("type", "")

        # Track user turns
        if event_type == "user" or "human" in event_type.lower():
            metrics.record_turn()

        # Track tool calls
        elif event_type == "tool_use" or "tool" in event_type.lower():
            tool_name = event.get("name", event.get("tool", "unknown"))

            # Check for errors in the event
            error = event.get("error")
            is_error = event.get("is_error", False)
            success = not (error or is_error)

            # Extract duration if available
            duration = event.get("duration_ms", 0)

            metrics.record_tool_call(
                tool_name=tool_name,
                success=success,
                duration_ms=duration,
                error=str(error) if error else None,
            )

    metrics.finalize()
    return metrics
