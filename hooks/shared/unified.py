#!/usr/bin/env python3
"""
Unified learning extraction and storage.
"""

import sys
from pathlib import Path
from typing import Optional

from .extraction import extract_learnings
from .ledger import append_block
from .paths import get_ledger_path


def extract_and_store_learnings(
    transcript_text: str,
    cwd: str,
    session_id: str,
    session_suffix: str = "",
) -> Optional[dict]:
    """Extract learnings from transcript text and store them in the ledger.

    This is the unified function for learning extraction used by both
    session_end.py and pre_compact.py hooks.

    Args:
        transcript_text: The text content from which to extract learnings
                        (typically assistant messages from transcript).
        cwd: Current working directory for determining ledger path.
        session_id: Session identifier for the block.
        session_suffix: Optional suffix to append to session_id (e.g., "-precompact").

    Returns:
        The created block dictionary, or None if no learnings were extracted.
    """
    # Extract learnings from the text
    learnings = extract_learnings(transcript_text)

    if not learnings:
        return None

    # Determine project directory
    project_dir = Path(cwd) if cwd else Path.cwd()

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
        print(
            f"[continuous-claude] Extracted {len(learnings)} learnings -> block {block['id']}",
            file=sys.stderr,
        )

    return block


__all__ = ["extract_and_store_learnings"]
