#!/usr/bin/env python3
"""
SessionEnd hook for claude-cortex.

Extracts learnings from the session transcript and stores them in the ledger.
"""

import json
import sys
from pathlib import Path
from uuid import uuid4

# Ensure shared module is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).parent))

from shared import (
    extract_and_store_learnings,
    extract_assistant_messages,
    get_learning_content,
    get_session_learnings_path,
    load_session_learnings,
    load_settings,
    read_json,
    read_transcript,
)
from shared.extraction import ExtractionSource


def get_learnings_without_recent_outcomes(
    learning_ids: list[str],
    cwd: str,
) -> list[dict]:
    """Get learnings that were referenced but have no recent outcomes.

    Args:
        learning_ids: List of 8-char learning ID prefixes
        cwd: Current working directory

    Returns:
        List of learning info dicts for those without recent outcomes
    """
    if not learning_ids:
        return []

    results = []
    project_dir = Path(cwd) if cwd else Path.cwd()

    # Check both project and global ledgers
    ledger_paths = [
        project_dir / ".claude" / "ledger",
        Path.home() / ".claude" / "ledger",
    ]

    for ledger_path in ledger_paths:
        reinforcements_file = ledger_path / "reinforcements.json"
        if not reinforcements_file.exists():
            continue

        reinforcements = read_json(reinforcements_file)
        learnings = reinforcements.get("learnings", {})

        for lid, info in learnings.items():
            lid_prefix = lid[:8].lower()
            if lid_prefix in [l.lower() for l in learning_ids]:
                # Check if there's a recent outcome (within last 7 days)
                outcome_count = info.get("outcome_count", 0)

                # Consider it "needs outcome" if:
                # 1. Never had an outcome, OR
                # 2. Low outcome count relative to potential usage
                if outcome_count < 3:  # Threshold for "needs more feedback"
                    # Get actual content from blocks
                    content = get_learning_content(ledger_path, lid)
                    results.append({
                        "id": lid[:8],
                        "full_id": lid,
                        "category": info.get("category", "unknown"),
                        "confidence": info.get("confidence", 0.5),
                        "outcome_count": outcome_count,
                        "content": content[:100] if content else "No content found",
                    })

    return results


def build_outcome_suggestion(referenced_learnings: list[dict]) -> str:
    """Build a suggestion message for recording outcomes.

    Args:
        referenced_learnings: List of learning info dicts

    Returns:
        Formatted suggestion message
    """
    if not referenced_learnings:
        return ""

    lines = [
        "",
        "---",
        "## Outcome Recording Suggestion",
        "",
        "The following learnings were referenced in this session and could benefit from outcome feedback:",
        "",
    ]

    for learning in referenced_learnings[:5]:  # Limit to 5 suggestions
        lines.append(f"- **[{learning['id']}]** ({learning['category']}, {int(learning['confidence']*100)}% confidence)")
        lines.append(f"  {learning['content']}...")
        lines.append("")

    lines.append("To record outcomes, run:")
    lines.append("```bash")
    lines.append("# If the learning helped:")
    lines.append(f"uv run cclaude outcome {referenced_learnings[0]['id']} -r success -c \"Brief description of how it helped\"")
    lines.append("")
    lines.append("# If it partially helped:")
    lines.append(f"uv run cclaude outcome {referenced_learnings[0]['id']} -r partial -c \"What worked and what needed adjustment\"")
    lines.append("")
    lines.append("# If it didn't work:")
    lines.append(f"uv run cclaude outcome {referenced_learnings[0]['id']} -r failure -c \"Why it didn't work\"")
    lines.append("```")
    lines.append("")
    lines.append("Or list all pending outcomes: `uv run cclaude outcomes pending`")
    lines.append("---")

    return "\n".join(lines)


def auto_promote_learnings(cwd: str, settings: dict) -> int:
    """Auto-promote high-confidence project learnings to global ledger.

    Criteria: confidence > threshold AND outcome_count >= min_outcomes AND privacy == public.

    Args:
        cwd: Current working directory.
        settings: Loaded settings dict.

    Returns:
        Number of learnings promoted.
    """
    promote_settings = settings.get("auto_promote", {})
    if not promote_settings.get("enabled", True):
        return 0

    min_confidence = promote_settings.get("min_confidence", 0.8)
    min_outcomes = promote_settings.get("min_outcome_count", 2)

    project_dir = Path(cwd) if cwd else Path.cwd()
    project_ledger_path = project_dir / ".claude" / "ledger"
    global_ledger_path = Path.home() / ".claude" / "ledger"

    if not project_ledger_path.exists() or not global_ledger_path.exists():
        return 0

    try:
        # Add src to path for imports
        src_path = Path(__file__).parent.parent / "src"
        if str(src_path) not in sys.path:
            sys.path.insert(0, str(src_path))

        from claude_cortex.ledger import Ledger

        project_ledger = Ledger(project_ledger_path)
        global_ledger = Ledger(global_ledger_path, is_global=True)

        # Get reinforcements to check outcome counts
        reinforcements = read_json(project_ledger_path / "reinforcements.json")
        learnings_data = reinforcements.get("learnings", {})

        # Filter by outcome count before calling promote
        # promote_to_global already handles confidence and privacy filters
        eligible_count = 0
        for lid, info in learnings_data.items():
            if (info.get("confidence", 0) >= min_confidence
                    and info.get("outcome_count", 0) >= min_outcomes):
                eligible_count += 1

        if eligible_count == 0:
            return 0

        promoted = project_ledger.promote_to_global(
            global_ledger,
            confidence_threshold=min_confidence,
        )

        # Filter promoted list to only those meeting outcome threshold
        # (promote_to_global doesn't check outcome_count, we do it here)
        actual_promoted = []
        for pid in promoted:
            info = learnings_data.get(pid, {})
            if info.get("outcome_count", 0) >= min_outcomes:
                actual_promoted.append(pid)

        if actual_promoted:
            print(
                f"[claude-cortex] SessionEnd: Auto-promoted {len(actual_promoted)} "
                f"learnings to global ledger",
                file=sys.stderr,
            )

        return len(actual_promoted)

    except Exception as e:
        print(f"[claude-cortex] SessionEnd: Auto-promote error: {e}", file=sys.stderr)
        return 0


def clear_session_learnings(path: Path) -> None:
    """Clear the session learnings file after processing."""
    try:
        if path.exists():
            path.unlink()
    except IOError:
        pass


def main():
    """Main hook entry point."""
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    session_id = input_data.get("session_id", str(uuid4()))
    transcript_path = input_data.get("transcript_path", "")
    cwd = input_data.get("cwd", "")

    # Skip if no transcript
    if not transcript_path:
        sys.exit(0)

    # Read and parse transcript
    events = read_transcript(transcript_path)
    if not events:
        sys.exit(0)

    # Extract assistant messages
    assistant_text = extract_assistant_messages(events)
    if not assistant_text:
        sys.exit(0)

    # Load settings to check for deep pass configuration
    project_dir = Path(cwd) if cwd else Path.cwd()
    settings = load_settings(project_dir)
    extraction_settings = settings.get("extraction", {})

    # Extract and store learnings using unified function
    # User-tagged learnings get higher confidence (0.70 default)
    extract_and_store_learnings(
        assistant_text,
        cwd,
        session_id,
        source=ExtractionSource.USER_TAGGED,
        enable_deep_pass=extraction_settings.get("enable_deep_pass", False),
        deep_pass_threshold=extraction_settings.get("deep_pass_threshold", 3),
    )

    # Auto-promote high-confidence learnings to global ledger
    try:
        auto_promote_learnings(cwd, settings)
    except Exception as e:
        print(f"[claude-cortex] SessionEnd: Auto-promote failed: {e}", file=sys.stderr)

    # Check for referenced learnings that need outcome feedback
    session_learnings_path = get_session_learnings_path(cwd)
    session_data = load_session_learnings(session_learnings_path)
    referenced_ids = session_data.get("referenced_learnings", [])

    if referenced_ids:
        # Find learnings that could use outcome feedback
        learnings_needing_outcomes = get_learnings_without_recent_outcomes(referenced_ids, cwd)

        if learnings_needing_outcomes:
            suggestion = build_outcome_suggestion(learnings_needing_outcomes)
            if suggestion:
                # Output suggestion to stderr so user sees it
                print(suggestion, file=sys.stderr)

        # Clear the session learnings file
        clear_session_learnings(session_learnings_path)

    sys.exit(0)


if __name__ == "__main__":
    main()
