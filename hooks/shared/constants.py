#!/usr/bin/env python3
"""
Constants and type definitions for shared utilities.
"""


class LearningCategory:
    """Learning category constants."""
    DISCOVERY = "discovery"
    DECISION = "decision"
    ERROR = "error"
    PATTERN = "pattern"


class PrivacyLevel:
    """Privacy level constants."""
    PUBLIC = "public"
    PROJECT = "project"
    PRIVATE = "private"
    REDACTED = "redacted"


__all__ = ["LearningCategory", "PrivacyLevel"]
