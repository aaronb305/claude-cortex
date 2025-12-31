"""Code entity extractors using tree-sitter."""

from claude_cortex.entities.extractors.base import BaseExtractor
from claude_cortex.entities.extractors.python import PythonExtractor
from claude_cortex.entities.extractors.typescript import TypeScriptExtractor

__all__ = [
    "BaseExtractor",
    "PythonExtractor",
    "TypeScriptExtractor",
]


def get_extractor_for_file(file_path: str) -> BaseExtractor | None:
    """Get the appropriate extractor for a file based on extension."""
    ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""

    if ext == "py":
        return PythonExtractor()
    elif ext in ("ts", "tsx", "js", "jsx"):
        return TypeScriptExtractor()

    return None
