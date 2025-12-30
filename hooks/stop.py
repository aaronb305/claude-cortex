#!/usr/bin/env python3
"""
Stop hook for continuous-claude-custom.

Detects significant work patterns in Claude's response and nudges for
immediate learning tagging. This is part of the hybrid learning capture
approach that combines:
1. Immediate tagging (CLAUDE.md instructions)
2. Pattern-based nudges (this hook)
3. PreCompact prompt injection
4. SessionEnd transcript analysis

The Stop hook fires after Claude finishes generating a response, making
it ideal for detecting when learnable moments have occurred.
"""

import json
import re
import sys
from pathlib import Path
from typing import Optional


# Patterns that suggest significant work was completed
SIGNIFICANT_WORK_PATTERNS = [
    # Bug fixes
    (r"(?:fixed|resolved|solved|corrected)\s+(?:the|a|an)?\s*(?:bug|issue|error|problem)", "bug_fix"),
    (r"the\s+(?:bug|issue|error)\s+was\s+(?:caused|due)", "bug_fix"),

    # Implementation completion
    (r"(?:implemented|added|created)\s+(?:the|a|an)?\s*(?:feature|function|method|class|component)", "implementation"),
    (r"(?:feature|implementation)\s+(?:is\s+)?(?:complete|done|finished)", "implementation"),

    # Architecture decisions
    (r"(?:decided|choosing|chose|going with)\s+(?:to\s+)?(?:use|implement)", "decision"),
    (r"(?:the\s+)?(?:approach|architecture|design|pattern)\s+(?:is|will be)", "decision"),

    # Error resolution
    (r"(?:the\s+)?error\s+(?:was|is)\s+(?:because|due to|caused by)", "error_discovery"),
    (r"(?:turns out|discovered|found out|realized)\s+(?:that\s+)?(?:the|it)", "error_discovery"),

    # Pattern identification
    (r"(?:this|the)\s+pattern\s+(?:can be|should be|is)\s+(?:used|applied|reused)", "pattern"),
    (r"(?:reusable|generalizable)\s+(?:solution|pattern|approach)", "pattern"),

    # Test fixes
    (r"(?:tests?|specs?)\s+(?:are\s+)?(?:now\s+)?(?:passing|green|fixed)", "test_fix"),

    # Refactoring
    (r"(?:refactored|restructured|reorganized|cleaned up)", "refactor"),
]

# Keywords that suggest learnable content
LEARNING_KEYWORDS = [
    "because", "the reason", "turns out", "discovered", "realized",
    "the trick is", "the key is", "important to note", "gotcha",
    "pitfall", "caveat", "workaround", "the fix", "the solution",
]

# Minimum response length to consider for nudging (avoid nudging short responses)
MIN_RESPONSE_LENGTH = 200

# Cooldown: Don't nudge if we recently nudged (tracked via file)
NUDGE_COOLDOWN_RESPONSES = 5


def get_nudge_state_path(cwd: str) -> Path:
    """Get path to nudge state file."""
    project_dir = Path(cwd) if cwd else Path.cwd()
    return project_dir / ".claude" / "nudge_state.json"


def load_nudge_state(path: Path) -> dict:
    """Load nudge state."""
    try:
        if path.exists():
            with open(path) as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError):
        pass
    return {"responses_since_nudge": 0, "last_nudge_type": None}


def save_nudge_state(path: Path, state: dict) -> None:
    """Save nudge state."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(state, f)
    except IOError:
        pass


def detect_significant_work(text: str) -> Optional[tuple[str, str]]:
    """Detect if the response contains significant work patterns.

    Args:
        text: The assistant's response text

    Returns:
        Tuple of (pattern_type, matched_text) or None
    """
    text_lower = text.lower()

    for pattern, work_type in SIGNIFICANT_WORK_PATTERNS:
        match = re.search(pattern, text_lower, re.IGNORECASE)
        if match:
            return (work_type, match.group(0))

    return None


def has_learning_keywords(text: str) -> bool:
    """Check if text contains keywords suggesting learnable content."""
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in LEARNING_KEYWORDS)


def already_has_tags(text: str) -> bool:
    """Check if the response already contains learning tags."""
    tag_patterns = [
        r'\[DISCOVERY\]',
        r'\[DECISION\]',
        r'\[ERROR\]',
        r'\[PATTERN\]',
    ]
    return any(re.search(p, text, re.IGNORECASE) for p in tag_patterns)


def build_nudge_message(work_type: str) -> str:
    """Build an appropriate nudge message based on work type."""
    nudges = {
        "bug_fix": (
            "💡 You just fixed a bug. Consider tagging the root cause:\n"
            "`[ERROR] <what caused it and how to avoid it>`"
        ),
        "implementation": (
            "💡 You completed an implementation. If you made any architectural choices, consider:\n"
            "`[DECISION] <what you chose and why>`"
        ),
        "decision": (
            "💡 You made a design decision. Consider capturing the rationale:\n"
            "`[DECISION] <the choice and reasoning>`"
        ),
        "error_discovery": (
            "💡 You discovered something about an error. Consider tagging it:\n"
            "`[ERROR] <what went wrong and how to avoid it>` or\n"
            "`[DISCOVERY] <what you learned>`"
        ),
        "pattern": (
            "💡 You identified a reusable pattern. Consider tagging it:\n"
            "`[PATTERN] <the generalizable solution>`"
        ),
        "test_fix": (
            "💡 Tests are passing now. If you learned why they were failing, consider:\n"
            "`[ERROR] <what caused the test failures>`"
        ),
        "refactor": (
            "💡 You completed a refactor. If there's a pattern worth remembering:\n"
            "`[PATTERN] <the refactoring approach used>`"
        ),
    }
    return nudges.get(work_type, "💡 Consider tagging any insights from this work.")


def extract_response_text(input_data: dict) -> str:
    """Extract text content from the stop hook input."""
    # The stop_hook receives the assistant's message
    message = input_data.get("message", {})

    if isinstance(message, str):
        return message

    if isinstance(message, dict):
        content = message.get("content", [])
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    text_parts.append(item)
            return "\n".join(text_parts)

    return ""


def main():
    """Main hook entry point."""
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    cwd = input_data.get("cwd", "")

    # Extract response text
    response_text = extract_response_text(input_data)

    # Skip if response is too short
    if len(response_text) < MIN_RESPONSE_LENGTH:
        sys.exit(0)

    # Skip if already has learning tags
    if already_has_tags(response_text):
        sys.exit(0)

    # Load nudge state for cooldown
    state_path = get_nudge_state_path(cwd)
    state = load_nudge_state(state_path)

    # Increment response counter
    state["responses_since_nudge"] = state.get("responses_since_nudge", 0) + 1

    # Check cooldown
    if state["responses_since_nudge"] < NUDGE_COOLDOWN_RESPONSES:
        save_nudge_state(state_path, state)
        sys.exit(0)

    # Detect significant work
    work_detection = detect_significant_work(response_text)

    # Also check for learning keywords as secondary signal
    has_keywords = has_learning_keywords(response_text)

    # Only nudge if we detect significant work AND learning keywords
    # This reduces false positives
    if work_detection and has_keywords:
        work_type, _ = work_detection
        nudge = build_nudge_message(work_type)

        # Reset cooldown
        state["responses_since_nudge"] = 0
        state["last_nudge_type"] = work_type
        save_nudge_state(state_path, state)

        # Output nudge (will be shown to user/injected)
        print(json.dumps({"message": nudge}))
    else:
        save_nudge_state(state_path, state)

    sys.exit(0)


if __name__ == "__main__":
    main()
