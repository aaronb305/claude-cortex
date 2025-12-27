"""Base extractor interface."""

from abc import ABC, abstractmethod

from ..ledger import Learning


class Extractor(ABC):
    """Base class for learning extractors."""

    @abstractmethod
    def extract(self, output: str) -> list[Learning]:
        """Extract learnings from Claude's output.

        Args:
            output: Claude's response text

        Returns:
            List of extracted learnings
        """
        pass
