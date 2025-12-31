#!/usr/bin/env python3
"""
Shared utilities for claude-cortex hooks.

This package consolidates all duplicated code from the hooks to provide
a single source of truth for common operations like ledger access,
transcript parsing, learning extraction, and handoff management.

File locking is used for all ledger write operations to prevent race conditions.

All exports are re-exported here for backward compatibility, so existing code
can use `from shared import ...` without modification.
"""

# Constants
from .constants import LearningCategory

# Path utilities
from .paths import get_ledger_path, get_search_db_path

# File locking
from .locking import file_lock

# JSON utilities
from .json_utils import read_json, write_json, read_json_locked, write_json_locked

# Ledger operations
from .ledger import (
    _init_package_imports,
    get_search_index,
    PACKAGE_AVAILABLE,
    ensure_ledger_structure,
    compute_block_hash,
    append_block,
    index_learnings_to_search,
    get_learnings_by_confidence,
    get_learning_content,
)

# Session learnings utilities
from .session import (
    get_session_learnings_path,
    load_session_learnings,
    save_session_learnings,
)

# Transcript utilities
from .transcript import read_transcript, extract_assistant_messages

# Learning extraction
from .extraction import (
    is_valid_learning,
    extract_learnings,
    extract_tasks_from_text,
    extract_blockers_from_text,
)

# Handoff management
from .handoff import save_handoff, load_latest_handoff, parse_handoff_markdown

# Git utilities
from .git import get_modified_files

# Project detection
from .project import detect_project_type

# Session analysis
from .analysis import (
    _init_analysis_imports,
    ANALYSIS_AVAILABLE,
    analyze_session,
    insights_to_learnings,
)

# Unified learning extraction
from .unified import extract_and_store_learnings


__all__ = [
    # Constants
    "LearningCategory",
    # Lazy init functions (preferred)
    "_init_package_imports",
    "_init_analysis_imports",
    "get_search_index",
    # Session learnings utilities
    "get_session_learnings_path",
    "load_session_learnings",
    "save_session_learnings",
    # Path utilities
    "get_ledger_path",
    "get_search_db_path",
    # File locking
    "file_lock",
    # JSON utilities
    "read_json",
    "write_json",
    "read_json_locked",
    "write_json_locked",
    # Ledger utilities
    "ensure_ledger_structure",
    "compute_block_hash",
    "append_block",
    "index_learnings_to_search",
    # Transcript utilities
    "read_transcript",
    "extract_assistant_messages",
    # Learning extraction
    "is_valid_learning",
    "extract_learnings",
    # Git utilities
    "get_modified_files",
    # Task extraction
    "extract_tasks_from_text",
    "extract_blockers_from_text",
    # Handoff management
    "save_handoff",
    "load_latest_handoff",
    "parse_handoff_markdown",
    # Project detection
    "detect_project_type",
    # Learning queries
    "get_learnings_by_confidence",
    "get_learning_content",
    # Session analysis
    "analyze_session",
    "insights_to_learnings",
    # Unified learning extraction
    "extract_and_store_learnings",
    # Backwards compatibility placeholders
    "PACKAGE_AVAILABLE",
    "ANALYSIS_AVAILABLE",
]
