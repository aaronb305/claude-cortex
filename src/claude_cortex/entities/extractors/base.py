"""Base class for code entity extractors."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Set

from claude_cortex.entities.models import ExtractionResult


class BaseExtractor(ABC):
    """Base class for language-specific entity extractors."""

    LANGUAGE: str = ""
    EXTENSIONS: Set[str] = set()

    @abstractmethod
    def extract_file(self, file_path: Path) -> ExtractionResult:
        """Extract entities and relationships from a file.

        Args:
            file_path: Path to the source file

        Returns:
            ExtractionResult containing entities, relationships, and any errors
        """
        pass

    def can_handle(self, file_path: Path) -> bool:
        """Check if this extractor can handle the given file.

        Args:
            file_path: Path to check

        Returns:
            True if the file extension is supported
        """
        suffix = file_path.suffix.lower()
        return suffix in self.EXTENSIONS
