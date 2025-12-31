#!/usr/bin/env python3
"""
Unified learning extraction and storage.

Supports confidence-weighted extraction with two-pass mode:
- Fast pass: Extract tagged content only (default)
- Deep pass: Run LLM analysis for additional insights (optional)
"""

import sys
from pathlib import Path
from typing import Optional

from .constants import PrivacyLevel
from .extraction import extract_learnings, ExtractionSource
from .ledger import append_block
from .paths import get_ledger_path
from .settings import load_settings


def extract_and_store_learnings(
    transcript_text: str,
    cwd: str,
    session_id: str,
    session_suffix: str = "",
    source: ExtractionSource = ExtractionSource.USER_TAGGED,
    enable_deep_pass: bool = False,
    deep_pass_threshold: int = 3,
) -> Optional[dict]:
    """Extract learnings from transcript text and store them in the ledger.

    This is the unified function for learning extraction used by both
    session_end.py and pre_compact.py hooks.

    Supports two-pass extraction:
    - Fast pass: Extract tagged content only (always runs)
    - Deep pass: Run LLM analysis for additional insights (optional)

    Args:
        transcript_text: The text content from which to extract learnings
                        (typically assistant messages from transcript).
        cwd: Current working directory for determining ledger path.
        session_id: Session identifier for the block.
        session_suffix: Optional suffix to append to session_id (e.g., "-precompact").
        source: The extraction source for confidence weighting.
                Defaults to USER_TAGGED for explicit tags.
        enable_deep_pass: If True and fast pass yields few results,
                         run LLM analysis for additional extraction.
        deep_pass_threshold: Trigger deep pass if fast pass yields fewer
                            than this many learnings.

    Returns:
        The created block dictionary, or None if no learnings were extracted.
    """
    # Determine project directory for settings
    project_dir = Path(cwd) if cwd else Path.cwd()

    # Load settings for confidence values
    settings = load_settings(project_dir)

    # Fast pass: Extract learnings from tagged content
    learnings = extract_learnings(transcript_text, source=source, settings=settings)

    # Deep pass: Run LLM analysis if enabled and fast pass yielded few results
    if enable_deep_pass and len(learnings) < deep_pass_threshold:
        try:
            from .analysis import analyze_session, insights_to_learnings, ANALYSIS_AVAILABLE

            if ANALYSIS_AVAILABLE:
                print(
                    f"[claude-cortex] Fast pass found {len(learnings)} learnings, running deep pass...",
                    file=sys.stderr,
                )
                # Run LLM analysis
                insights = analyze_session(transcript_text)
                if insights:
                    # Convert insights to learnings with LLM_ANALYSIS confidence
                    llm_learnings = insights_to_learnings(insights)
                    # Set extraction source and confidence for LLM-extracted learnings
                    llm_confidence = settings.get("extraction", {}).get(
                        "llm_analysis_confidence", 0.40
                    )
                    for learning in llm_learnings:
                        learning["extraction_source"] = ExtractionSource.LLM_ANALYSIS.value
                        learning["confidence"] = llm_confidence
                    learnings.extend(llm_learnings)
                    print(
                        f"[claude-cortex] Deep pass added {len(llm_learnings)} learnings",
                        file=sys.stderr,
                    )
        except ImportError:
            pass  # Analysis not available

    if not learnings:
        return None

    # Filter out private learnings (they should never be persisted)
    # Private learnings are extracted but not stored
    private_count = sum(1 for l in learnings if l.get("privacy") == PrivacyLevel.PRIVATE)
    learnings = [l for l in learnings if l.get("privacy") != PrivacyLevel.PRIVATE]

    if private_count > 0:
        print(
            f"[claude-cortex] Filtered {private_count} private learnings (not stored)",
            file=sys.stderr,
        )

    if not learnings:
        return None

    # Check if we're in a project with a .claude directory or project files
    if (
        (project_dir / ".claude").exists()
        or (project_dir / "pyproject.toml").exists()
        or (project_dir / "package.json").exists()
    ):
        ledger_path = get_ledger_path(str(project_dir), is_global=False)
    else:
        # Use global ledger
        ledger_path = get_ledger_path(None, is_global=True)

    # Append block with optional session suffix
    block_session_id = session_id + session_suffix if session_suffix else session_id
    block = append_block(ledger_path, block_session_id, learnings)

    if block:
        extraction_sources = set(l.get("extraction_source", "unknown") for l in learnings)
        sources_str = ", ".join(sorted(extraction_sources))
        print(
            f"[claude-cortex] Extracted {len(learnings)} learnings (sources: {sources_str}) -> block {block['id']}",
            file=sys.stderr,
        )

    return block


__all__ = ["extract_and_store_learnings", "ExtractionSource"]
