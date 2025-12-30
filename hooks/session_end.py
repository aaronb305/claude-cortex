#!/usr/bin/env python3
"""
SessionEnd hook for continuous-claude-custom.

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
    read_json,
    read_transcript,
)


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

    # Extract and store learnings using unified function
    extract_and_store_learnings(assistant_text, cwd, session_id)

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
