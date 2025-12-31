"""Extraction patterns for git ingestion."""

import re
from claude_cortex.ledger.models import LearningCategory

# Explicit learning tags in commit messages
EXPLICIT_TAG_PATTERNS: dict[LearningCategory, re.Pattern] = {
    LearningCategory.DISCOVERY: re.compile(
        r"\[DISCOVERY\](?::[\w]+)?\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
        re.DOTALL | re.IGNORECASE,
    ),
    LearningCategory.DECISION: re.compile(
        r"\[DECISION\](?::[\w]+)?\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
        re.DOTALL | re.IGNORECASE,
    ),
    LearningCategory.ERROR: re.compile(
        r"\[ERROR\](?::[\w]+)?\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
        re.DOTALL | re.IGNORECASE,
    ),
    LearningCategory.PATTERN: re.compile(
        r"\[PATTERN\](?::[\w]+)?\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
        re.DOTALL | re.IGNORECASE,
    ),
}

# Conventional commit pattern: type(scope): description
CONVENTIONAL_COMMIT_PATTERN = re.compile(
    r"^(feat|fix|refactor|perf|test|docs|style|build|ci|chore)(?:\(([^)]+)\))?\s*!?:\s*(.+)",
    re.IGNORECASE | re.MULTILINE,
)

# Map conventional commit types to learning categories
COMMIT_TYPE_TO_CATEGORY: dict[str, LearningCategory | None] = {
    "feat": LearningCategory.DISCOVERY,     # New feature = discovery
    "fix": LearningCategory.ERROR,          # Bug fix = what went wrong
    "refactor": LearningCategory.PATTERN,   # Refactoring = pattern
    "perf": LearningCategory.PATTERN,       # Performance = pattern
    "test": LearningCategory.PATTERN,       # Testing = pattern
    "docs": LearningCategory.DECISION,      # Documentation = decision
    "style": None,                          # Skip style changes
    "build": None,                          # Skip build changes
    "ci": None,                             # Skip CI changes
    "chore": None,                          # Skip chores
}

# Co-Authored-By trailer pattern
CO_AUTHOR_PATTERN = re.compile(
    r"Co-Authored-By:\s*(.+?)\s*<([^>]+)>",
    re.IGNORECASE | re.MULTILINE,
)

# PR insight patterns for extracting from descriptions/reviews
PR_INSIGHT_PATTERNS = {
    "what_changed": re.compile(
        r"##?\s*(?:What|Changes|Summary)\s*\n(.+?)(?=\n##|\Z)",
        re.DOTALL | re.IGNORECASE,
    ),
    "why_changed": re.compile(
        r"##?\s*(?:Why|Motivation|Rationale|Context)\s*\n(.+?)(?=\n##|\Z)",
        re.DOTALL | re.IGNORECASE,
    ),
    "breaking_changes": re.compile(
        r"##?\s*(?:Breaking|Migration)\s*\n(.+?)(?=\n##|\Z)",
        re.DOTALL | re.IGNORECASE,
    ),
}

# Minimum message length for conventional commit extraction (skip trivial commits)
MIN_MESSAGE_LENGTH = 20

# Confidence values for different extraction sources
CONFIDENCE_EXPLICIT_TAG = 0.65
CONFIDENCE_CONVENTIONAL_COMMIT = 0.55
CONFIDENCE_PR_DESCRIPTION = 0.50
CONFIDENCE_PR_REVIEW = 0.45

# Confidence adjustments
CONFIDENCE_BOOST_DETAILED = 0.05      # Message > 100 chars
CONFIDENCE_BOOST_COAUTHORED = 0.05    # Has co-authors
CONFIDENCE_BOOST_VERY_DETAILED = 0.10 # Message > 200 chars
