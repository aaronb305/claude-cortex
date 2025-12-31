#!/usr/bin/env python3
"""
Learning extraction and validation utilities.
"""

import re
from uuid import uuid4

from .constants import LearningCategory


def is_valid_learning(content: str) -> bool:
    """Check if content looks like a valid learning vs noise.

    Applies heuristics to filter out markdown artifacts, code snippets,
    and other non-learning content, while allowing technical content
    with backticks, parentheses, and common code references.

    Args:
        content: The extracted content to validate.

    Returns:
        True if the content appears to be a valid learning.
    """
    if not content:
        return False

    # Reject if it looks like a markdown table
    if content.count("|") > 2:
        return False

    # Count alphanumeric + common punctuation as valid characters
    # This is more lenient to allow backticks, parentheses, brackets for code refs
    valid_chars = sum(
        c.isalnum() or c.isspace() or c in ".,;:!?'-()[]{}\"`_"
        for c in content
    )
    if valid_chars / max(len(content), 1) < 0.5:
        return False

    # Reject if it starts with markdown formatting artifacts
    if content.startswith(("-", "*", "|", "#", "```")):
        return False

    # Be more lenient with parentheses/braces - only reject if clearly code block
    # (e.g., more than 5 open parens or 4 open braces suggests raw code)
    if content.count("(") > 5 or content.count("{") > 4:
        return False

    # Must have some actual words
    words = [w for w in content.split() if len(w) > 2 and w.isalpha()]
    if len(words) < 3:
        return False

    return True


# Compiled regex patterns for learning extraction
_LEARNING_PATTERNS = {
    LearningCategory.DISCOVERY: re.compile(
        r"(?:^|\n)\s*\[DISCOVERY\]\s*([^\n\[]+?)(?:\.|$|\n|\[)",
        re.IGNORECASE,
    ),
    LearningCategory.DECISION: re.compile(
        r"(?:^|\n)\s*\[DECISION\]\s*([^\n\[]+?)(?:\.|$|\n|\[)",
        re.IGNORECASE,
    ),
    LearningCategory.ERROR: re.compile(
        r"(?:^|\n)\s*\[ERROR\]\s*([^\n\[]+?)(?:\.|$|\n|\[)",
        re.IGNORECASE,
    ),
    LearningCategory.PATTERN: re.compile(
        r"(?:^|\n)\s*\[PATTERN\]\s*([^\n\[]+?)(?:\.|$|\n|\[)",
        re.IGNORECASE,
    ),
}


def extract_learnings(text: str) -> list[dict]:
    """Extract learnings from text using tagged patterns.

    Looks for [DISCOVERY], [DECISION], [ERROR], and [PATTERN] tags
    and extracts the associated content.

    Args:
        text: Text to extract learnings from (typically assistant messages).

    Returns:
        List of learning dictionaries with id, category, content, confidence,
        source, and outcomes fields.
    """
    learnings = []
    seen_content = set()

    for category, pattern in _LEARNING_PATTERNS.items():
        matches = pattern.findall(text)
        for match in matches:
            content = match.strip()
            # Clean up the content
            content = re.sub(r"\s+", " ", content)
            content = content[:500]  # Limit length

            # Validate the content looks like a real learning
            if not content or len(content) < 20 or content in seen_content:
                continue
            if not is_valid_learning(content):
                continue

            seen_content.add(content)

            # Try to extract source file reference
            source = None
            file_match = re.search(
                r"(?:in|from|at|see)\s+([a-zA-Z0-9_\-./]+\.[a-zA-Z]+)",
                content
            )
            if file_match:
                source = file_match.group(1)

            learnings.append({
                "id": str(uuid4()),
                "category": category,
                "content": content,
                "confidence": 0.5,
                "source": source,
                "outcomes": [],
            })

    return learnings


# Compiled patterns for task extraction
_COMPLETED_PATTERNS = [
    re.compile(
        r"(?:completed|done|finished|implemented|created|added|fixed|updated):\s*(.+?)(?:\n|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"I(?:'ve| have)\s+(?:completed|done|finished|implemented|created|added|fixed|updated)\s+(.+?)(?:\.|$)",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*-\s*\[x\]\s*(.+?)$", re.MULTILINE),
]

_PENDING_PATTERNS = [
    re.compile(
        r"(?:todo|remaining|still need to|next|pending):\s*(.+?)(?:\n|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:still need to|should still|remaining to)\s+(.+?)(?:\.|$)",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*-\s*\[\s*\]\s*(.+?)$", re.MULTILINE),
]


def extract_tasks_from_text(text: str) -> tuple[list[str], list[str]]:
    """Extract completed and pending tasks from assistant text.

    Looks for common task patterns in the text, including markdown checkboxes
    and natural language patterns.

    Args:
        text: The assistant messages text.

    Returns:
        Tuple of (completed_tasks, pending_tasks), each limited to 10 items.
    """
    completed = []
    pending = []

    for pattern in _COMPLETED_PATTERNS:
        matches = pattern.findall(text)
        for match in matches:
            task = match.strip()[:200]  # Limit length
            if task and len(task) > 10:
                completed.append(task)

    for pattern in _PENDING_PATTERNS:
        matches = pattern.findall(text)
        for match in matches:
            task = match.strip()[:200]
            if task and len(task) > 10:
                pending.append(task)

    # Deduplicate while preserving order
    return list(dict.fromkeys(completed))[:10], list(dict.fromkeys(pending))[:10]


# Compiled patterns for blocker extraction
_BLOCKER_PATTERNS = [
    re.compile(
        r"(?:blocked by|blocker|blocking issue|cannot proceed|waiting for):\s*(.+?)(?:\n|$)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:issue|problem|error):\s*(.+?)(?:\n|$)",
        re.IGNORECASE,
    ),
]


def extract_blockers_from_text(text: str) -> list[str]:
    """Extract blockers from assistant text.

    Looks for patterns indicating blocking issues or problems.

    Args:
        text: The assistant messages text.

    Returns:
        List of blockers, limited to 5 items.
    """
    blockers = []

    for pattern in _BLOCKER_PATTERNS:
        matches = pattern.findall(text)
        for match in matches:
            blocker = match.strip()[:200]
            if blocker and len(blocker) > 10:
                blockers.append(blocker)

    return list(dict.fromkeys(blockers))[:5]


__all__ = [
    "is_valid_learning",
    "extract_learnings",
    "extract_tasks_from_text",
    "extract_blockers_from_text",
]
