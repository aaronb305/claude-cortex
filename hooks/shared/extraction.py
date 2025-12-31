#!/usr/bin/env python3
"""
Learning extraction and validation utilities.

Supports confidence-weighted extraction where different extraction sources
get different default confidence levels:
- USER_TAGGED: 0.70 (user explicitly tagged with [DISCOVERY], etc.)
- STOP_HOOK: 0.50 (auto-detected by stop hook patterns)
- LLM_ANALYSIS: 0.40 (extracted by LLM session analysis)
- CONSENSUS: 0.85 (confirmed by multiple sources)
"""

import re
from enum import Enum
from typing import Optional
from uuid import uuid4

from .constants import LearningCategory, PrivacyLevel


class ExtractionSource(str, Enum):
    """Source of learning extraction for confidence weighting."""

    USER_TAGGED = "user_tagged"  # User explicitly tagged: 0.70 default
    STOP_HOOK = "stop_hook"  # Auto-detected by patterns: 0.50 default
    LLM_ANALYSIS = "llm_analysis"  # AI extracted from transcript: 0.40 default
    CONSENSUS = "consensus"  # Multiple sources agree: 0.85 default


# Default confidence by extraction source
DEFAULT_SOURCE_CONFIDENCE = {
    ExtractionSource.USER_TAGGED: 0.70,
    ExtractionSource.STOP_HOOK: 0.50,
    ExtractionSource.LLM_ANALYSIS: 0.40,
    ExtractionSource.CONSENSUS: 0.85,
}


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


# Valid privacy levels for validation
_VALID_PRIVACY_LEVELS = {
    PrivacyLevel.PUBLIC,
    PrivacyLevel.PROJECT,
    PrivacyLevel.PRIVATE,
    PrivacyLevel.REDACTED,
}


def _parse_privacy_level(privacy_str: Optional[str]) -> str:
    """Parse and validate a privacy level string.

    Args:
        privacy_str: The privacy level string (e.g., "private", "project").
                    If None or invalid, defaults to PUBLIC.

    Returns:
        A valid privacy level string.
    """
    if not privacy_str:
        return PrivacyLevel.PUBLIC
    normalized = privacy_str.lower().strip()
    if normalized in _VALID_PRIVACY_LEVELS:
        return normalized
    return PrivacyLevel.PUBLIC


# Compiled regex patterns for learning extraction
# Pattern captures: category name, optional privacy suffix, content
# Examples:
#   [DISCOVERY] Some insight -> category=discovery, privacy=public
#   [DISCOVERY:private] Some insight -> category=discovery, privacy=private
#   [PATTERN:project] Some pattern -> category=pattern, privacy=project
_LEARNING_PATTERNS_WITH_PRIVACY = {
    LearningCategory.DISCOVERY: re.compile(
        r"(?:^|\n)\s*\[DISCOVERY(?::(\w+))?\]\s*([^\n\[]+?)(?:\.|$|\n|\[)",
        re.IGNORECASE,
    ),
    LearningCategory.DECISION: re.compile(
        r"(?:^|\n)\s*\[DECISION(?::(\w+))?\]\s*([^\n\[]+?)(?:\.|$|\n|\[)",
        re.IGNORECASE,
    ),
    LearningCategory.ERROR: re.compile(
        r"(?:^|\n)\s*\[ERROR(?::(\w+))?\]\s*([^\n\[]+?)(?:\.|$|\n|\[)",
        re.IGNORECASE,
    ),
    LearningCategory.PATTERN: re.compile(
        r"(?:^|\n)\s*\[PATTERN(?::(\w+))?\]\s*([^\n\[]+?)(?:\.|$|\n|\[)",
        re.IGNORECASE,
    ),
}


def get_confidence_for_source(
    source: ExtractionSource,
    settings: Optional[dict] = None,
) -> float:
    """Get the confidence value for an extraction source.

    Uses settings if provided, otherwise falls back to defaults.

    Args:
        source: The extraction source.
        settings: Optional settings dict (from load_settings()).

    Returns:
        Confidence value between 0 and 1.
    """
    # Try to get from settings first
    if settings:
        extraction_settings = settings.get("extraction", {})
        setting_keys = {
            ExtractionSource.USER_TAGGED: "user_tagged_confidence",
            ExtractionSource.STOP_HOOK: "stop_hook_confidence",
            ExtractionSource.LLM_ANALYSIS: "llm_analysis_confidence",
            ExtractionSource.CONSENSUS: "consensus_confidence",
        }
        key = setting_keys.get(source)
        if key and key in extraction_settings:
            return extraction_settings[key]

    # Fall back to defaults
    return DEFAULT_SOURCE_CONFIDENCE.get(source, 0.5)


def extract_learnings(
    text: str,
    source: ExtractionSource = ExtractionSource.USER_TAGGED,
    settings: Optional[dict] = None,
) -> list[dict]:
    """Extract learnings from text using tagged patterns.

    Looks for [DISCOVERY], [DECISION], [ERROR], and [PATTERN] tags
    (with optional privacy suffix like :private, :project, :redacted)
    and extracts the associated content.

    Privacy levels:
    - public (default): Normal learning, can be promoted to global
    - project: Stays in project ledger only
    - private: Never persisted (filtered out before storage)
    - redacted: Logged as redacted (content replaced with placeholder)

    Args:
        text: Text to extract learnings from (typically assistant messages).
        source: The extraction source for confidence weighting.
                Defaults to USER_TAGGED for explicit tags.
        settings: Optional settings dict for confidence values.
                  If None, uses DEFAULT_SOURCE_CONFIDENCE.

    Returns:
        List of learning dictionaries with id, category, content, confidence,
        source, extraction_source, privacy, and outcomes fields.
    """
    learnings = []
    seen_content = set()

    # Get confidence based on extraction source
    confidence = get_confidence_for_source(source, settings)

    for category, pattern in _LEARNING_PATTERNS_WITH_PRIVACY.items():
        matches = pattern.findall(text)
        for privacy_str, content in matches:
            content = content.strip()
            # Clean up the content
            content = re.sub(r"\s+", " ", content)
            content = content[:500]  # Limit length

            # Validate the content looks like a real learning
            if not content or len(content) < 20 or content in seen_content:
                continue
            if not is_valid_learning(content):
                continue

            seen_content.add(content)

            # Parse privacy level from suffix
            privacy = _parse_privacy_level(privacy_str)

            # Handle redacted learnings: replace content with placeholder
            if privacy == PrivacyLevel.REDACTED:
                content = "[REDACTED]"

            # Try to extract source file reference
            file_source = None
            file_match = re.search(
                r"(?:in|from|at|see)\s+([a-zA-Z0-9_\-./]+\.[a-zA-Z]+)",
                content
            )
            if file_match:
                file_source = file_match.group(1)

            learnings.append({
                "id": str(uuid4()),
                "category": category,
                "content": content,
                "confidence": confidence,
                "source": file_source,
                "extraction_source": source.value,
                "privacy": privacy,
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
    "ExtractionSource",
    "DEFAULT_SOURCE_CONFIDENCE",
    "get_confidence_for_source",
    "is_valid_learning",
    "extract_learnings",
    "extract_tasks_from_text",
    "extract_blockers_from_text",
]
