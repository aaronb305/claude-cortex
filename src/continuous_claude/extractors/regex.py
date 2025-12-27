"""Regex-based extractor for structured learning tags."""

import re
from typing import Optional

from ..ledger import Learning, LearningCategory
from .base import Extractor


class RegexExtractor(Extractor):
    """Extracts learnings using regex patterns for tagged output."""

    def __init__(self):
        # Patterns for different learning categories
        self.patterns = {
            LearningCategory.DISCOVERY: re.compile(
                r"\[DISCOVERY\]\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
                re.DOTALL | re.IGNORECASE,
            ),
            LearningCategory.DECISION: re.compile(
                r"\[DECISION\]\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
                re.DOTALL | re.IGNORECASE,
            ),
            LearningCategory.ERROR: re.compile(
                r"\[ERROR\]\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
                re.DOTALL | re.IGNORECASE,
            ),
            LearningCategory.PATTERN: re.compile(
                r"\[PATTERN\]\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
                re.DOTALL | re.IGNORECASE,
            ),
        }

        # Alternative patterns for inline format
        self.inline_patterns = {
            LearningCategory.DISCOVERY: re.compile(
                r"(?:learned|discovered|found)(?:\s+that)?:?\s*(.+?)(?:\.|$)",
                re.IGNORECASE,
            ),
            LearningCategory.DECISION: re.compile(
                r"(?:decided|choosing|will use|going with):?\s*(.+?)(?:\.|$)",
                re.IGNORECASE,
            ),
            LearningCategory.ERROR: re.compile(
                r"(?:avoid|don't|shouldn't|gotcha|warning):?\s*(.+?)(?:\.|$)",
                re.IGNORECASE,
            ),
            LearningCategory.PATTERN: re.compile(
                r"(?:pattern|convention|always|typically):?\s*(.+?)(?:\.|$)",
                re.IGNORECASE,
            ),
        }

    def _extract_source(self, content: str) -> Optional[str]:
        """Try to extract a source file reference from content.

        Args:
            content: Learning content

        Returns:
            File path if found, None otherwise
        """
        # Look for file paths
        file_pattern = re.compile(r"(?:in|from|at|see)\s+([a-zA-Z0-9_\-./]+\.[a-zA-Z]+)")
        match = file_pattern.search(content)
        if match:
            return match.group(1)
        return None

    def extract(self, output: str) -> list[Learning]:
        """Extract learnings from Claude's output.

        Args:
            output: Claude's response text

        Returns:
            List of extracted learnings
        """
        learnings = []
        seen_content = set()

        # First try structured tags
        for category, pattern in self.patterns.items():
            matches = pattern.findall(output)
            for match in matches:
                content = match.strip()
                if content and content not in seen_content:
                    seen_content.add(content)
                    source = self._extract_source(content)
                    learnings.append(Learning(
                        category=category,
                        content=content,
                        source=source,
                        confidence=0.6,  # Higher initial confidence for explicit tags
                    ))

        # If no structured learnings found, try inline patterns
        if not learnings:
            for category, pattern in self.inline_patterns.items():
                matches = pattern.findall(output)
                for match in matches:
                    content = match.strip()
                    # Filter out too-short or too-long matches
                    if len(content) < 20 or len(content) > 500:
                        continue
                    if content and content not in seen_content:
                        seen_content.add(content)
                        source = self._extract_source(content)
                        learnings.append(Learning(
                            category=category,
                            content=content,
                            source=source,
                            confidence=0.4,  # Lower confidence for implicit extraction
                        ))

        return learnings
