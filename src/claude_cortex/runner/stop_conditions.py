"""Pluggable stopping conditions for the execution loop."""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Optional

from ..ledger import Ledger


class StopCondition(ABC):
    """Base class for stopping conditions."""

    @abstractmethod
    def should_stop(self, iteration: int, state: dict) -> tuple[bool, str]:
        """Check if execution should stop.

        Args:
            iteration: Current iteration number
            state: Current execution state

        Returns:
            Tuple of (should_stop, reason)
        """
        pass

    @abstractmethod
    def reset(self) -> None:
        """Reset the condition for a new run."""
        pass


class IterationLimit(StopCondition):
    """Stop after a maximum number of iterations."""

    def __init__(self, max_iterations: int):
        self.max_iterations = max_iterations

    def should_stop(self, iteration: int, state: dict) -> tuple[bool, str]:
        if iteration >= self.max_iterations:
            return True, f"Reached maximum iterations ({self.max_iterations})"
        return False, ""

    def reset(self) -> None:
        pass


class CostLimit(StopCondition):
    """Stop after exceeding a cost budget."""

    def __init__(self, max_cost_usd: float):
        self.max_cost_usd = max_cost_usd
        self.total_cost = 0.0

    def should_stop(self, iteration: int, state: dict) -> tuple[bool, str]:
        self.total_cost = state.get("total_cost", 0.0)
        if self.total_cost >= self.max_cost_usd:
            return True, f"Exceeded cost budget (${self.total_cost:.2f} >= ${self.max_cost_usd:.2f})"
        return False, ""

    def reset(self) -> None:
        self.total_cost = 0.0


class TimeLimit(StopCondition):
    """Stop after a duration has elapsed."""

    def __init__(self, duration: timedelta):
        self.duration = duration
        self.start_time: Optional[datetime] = None

    def should_stop(self, iteration: int, state: dict) -> tuple[bool, str]:
        if self.start_time is None:
            self.start_time = datetime.now(timezone.utc)

        elapsed = datetime.now(timezone.utc) - self.start_time
        if elapsed >= self.duration:
            return True, f"Time limit reached ({elapsed} >= {self.duration})"
        return False, ""

    def reset(self) -> None:
        self.start_time = None


class NoNewLearnings(StopCondition):
    """Stop when no new learnings are produced for N iterations."""

    def __init__(self, max_stale_iterations: int = 3):
        self.max_stale_iterations = max_stale_iterations
        self.stale_count = 0
        self.last_learning_count = 0

    def should_stop(self, iteration: int, state: dict) -> tuple[bool, str]:
        current_count = state.get("total_learnings", 0)

        if current_count == self.last_learning_count:
            self.stale_count += 1
        else:
            self.stale_count = 0
            self.last_learning_count = current_count

        if self.stale_count >= self.max_stale_iterations:
            return True, f"No new learnings for {self.max_stale_iterations} iterations"
        return False, ""

    def reset(self) -> None:
        self.stale_count = 0
        self.last_learning_count = 0


class ConfidenceThreshold(StopCondition):
    """Stop when a specific learning reaches a confidence threshold."""

    def __init__(
        self,
        ledger: Ledger,
        target_content: str,
        threshold: float = 0.9,
    ):
        self.ledger = ledger
        self.target_content = target_content.lower()
        self.threshold = threshold

    def should_stop(self, iteration: int, state: dict) -> tuple[bool, str]:
        high_confidence = self.ledger.get_learnings_by_confidence(
            min_confidence=self.threshold
        )

        for learning_info in high_confidence:
            for block in self.ledger.get_all_blocks():
                for learning in block.learnings:
                    if learning.id == learning_info["id"]:
                        if self.target_content in learning.content.lower():
                            return True, f"Target learning reached {self.threshold*100}% confidence"
        return False, ""

    def reset(self) -> None:
        pass


class CompositeStopCondition(StopCondition):
    """Combines multiple stop conditions (stops if ANY condition is met)."""

    def __init__(self, conditions: list[StopCondition]):
        self.conditions = conditions

    def should_stop(self, iteration: int, state: dict) -> tuple[bool, str]:
        for condition in self.conditions:
            should_stop, reason = condition.should_stop(iteration, state)
            if should_stop:
                return True, reason
        return False, ""

    def reset(self) -> None:
        for condition in self.conditions:
            condition.reset()
