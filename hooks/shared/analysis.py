#!/usr/bin/env python3
"""
LLM-powered session analysis utilities.
"""

import sys
from pathlib import Path
from typing import Optional


# Lazy imports for analysis functionality
_ANALYSIS_AVAILABLE: Optional[bool] = None
_TranscriptAnalyzer = None
_SessionInsights = None


def _init_analysis_imports():
    """Lazily initialize analysis imports (triggers ML dependencies)."""
    global _ANALYSIS_AVAILABLE, _TranscriptAnalyzer, _SessionInsights

    if _ANALYSIS_AVAILABLE is not None:
        return _ANALYSIS_AVAILABLE

    # First ensure package is available
    try:
        _src_path = Path(__file__).parent.parent.parent / "src"
        if _src_path.exists() and str(_src_path) not in sys.path:
            sys.path.insert(0, str(_src_path))

        from claude_cortex.analysis import TranscriptAnalyzer, SessionInsights
        _TranscriptAnalyzer = TranscriptAnalyzer
        _SessionInsights = SessionInsights
        _ANALYSIS_AVAILABLE = True
    except ImportError:
        _TranscriptAnalyzer = None
        _SessionInsights = None
        _ANALYSIS_AVAILABLE = False

    return _ANALYSIS_AVAILABLE


# For backwards compatibility
ANALYSIS_AVAILABLE = None  # Placeholder - use _init_analysis_imports() instead


def analyze_session(
    transcript_path: str,
    session_id: str,
    use_llm: bool = True,
    save_insights: bool = True,
    project_dir: Optional[Path] = None,
) -> Optional[dict]:
    """Analyze a session transcript and extract structured insights.

    This provides Braintrust-like learning extraction using LLM analysis
    of the full transcript, not just tagged content.

    Args:
        transcript_path: Path to the transcript file.
        session_id: Session identifier.
        use_llm: Whether to use LLM for analysis (vs regex fallback).
        save_insights: Whether to save insights to disk.
        project_dir: Project directory for saving insights.

    Returns:
        Dictionary with insights, or None if analysis failed.
    """
    if not _init_analysis_imports():
        return None

    try:
        transcript_file = Path(transcript_path)
        if not transcript_file.exists():
            return None

        # Create analyzer (lazy import already done)
        analyzer = _TranscriptAnalyzer(use_llm=use_llm)

        # Analyze transcript
        insights = analyzer.analyze_from_file(transcript_file, session_id)

        # Save insights if requested
        if save_insights and project_dir:
            insights_dir = project_dir / ".claude" / "insights" / session_id
            from claude_cortex.analysis.transcript import save_insights as _save
            _save(insights, insights_dir)

        return insights.to_dict()
    except Exception as e:
        print(f"[claude-cortex] Warning: Session analysis failed: {e}", file=sys.stderr)
        return None


def insights_to_learnings(insights_dict: dict) -> list[dict]:
    """Convert session insights to learning format for ledger storage.

    Args:
        insights_dict: Dictionary from analyze_session()

    Returns:
        List of learning dicts ready for append_block()
    """
    if not _init_analysis_imports() or not insights_dict:
        return []

    try:
        insights = _SessionInsights(
            session_id=insights_dict.get("session_id", "unknown"),
            what_worked=insights_dict.get("what_worked", []),
            what_failed=insights_dict.get("what_failed", []),
            patterns=insights_dict.get("patterns", []),
            key_decisions=insights_dict.get("key_decisions", []),
        )
        return insights.to_learnings()
    except Exception as e:
        print(f"[claude-cortex] Warning: Failed to convert insights to learnings: {e}", file=sys.stderr)
        return []


__all__ = [
    "_init_analysis_imports",
    "ANALYSIS_AVAILABLE",
    "analyze_session",
    "insights_to_learnings",
]
