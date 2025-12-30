"""Session analysis module - LLM-powered learning extraction.

This module provides Braintrust-like capabilities locally:
- Full transcript analysis (not just tagged content)
- Structured insights: What Worked / What Failed / Patterns
- Tool usage analytics and success/failure tracking
- Automatic learning extraction without explicit tagging
"""

from .transcript import TranscriptAnalyzer, SessionInsights
from .metrics import ToolMetrics, SessionMetrics

__all__ = [
    "TranscriptAnalyzer",
    "SessionInsights",
    "ToolMetrics",
    "SessionMetrics",
]
