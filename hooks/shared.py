#!/usr/bin/env python3
"""
Shared utilities for claude-cortex hooks.

This module consolidates all duplicated code from the hooks to provide
a single source of truth for common operations like ledger access,
transcript parsing, learning extraction, and handoff management.

File locking is used for all ledger write operations to prevent race conditions.

NOTE: This file is a re-export hub for backward compatibility.
The actual implementations live in the shared/ submodule.
"""

# Re-export everything from the shared package for backward compatibility
from shared import (
    # Constants
    LearningCategory,
    # Lazy init functions (preferred)
    _init_package_imports,
    _init_analysis_imports,
    get_search_index,
    # Session learnings utilities
    get_session_learnings_path,
    load_session_learnings,
    save_session_learnings,
    # Path utilities
    get_ledger_path,
    get_search_db_path,
    # File locking
    file_lock,
    # JSON utilities
    read_json,
    write_json,
    read_json_locked,
    write_json_locked,
    # Ledger utilities
    ensure_ledger_structure,
    compute_block_hash,
    append_block,
    index_learnings_to_search,
    # Transcript utilities
    read_transcript,
    extract_assistant_messages,
    # Learning extraction
    is_valid_learning,
    extract_learnings,
    # Git utilities
    get_modified_files,
    # Task extraction
    extract_tasks_from_text,
    extract_blockers_from_text,
    # Handoff management
    save_handoff,
    load_latest_handoff,
    parse_handoff_markdown,
    # Project detection
    detect_project_type,
    # Learning queries
    get_learnings_by_confidence,
    get_learning_content,
    # Session analysis
    analyze_session,
    insights_to_learnings,
    # Unified learning extraction
    extract_and_store_learnings,
    # Backwards compatibility placeholders
    PACKAGE_AVAILABLE,
    ANALYSIS_AVAILABLE,
)


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
