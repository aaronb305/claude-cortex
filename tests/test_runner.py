"""Tests for the runner module."""

import pytest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import json
import tempfile

from continuous_claude.runner.stop_conditions import (
    StopCondition,
    IterationLimit,
    CostLimit,
    TimeLimit,
    NoNewLearnings,
    ConfidenceThreshold,
    CompositeStopCondition,
)
from continuous_claude.runner.context import ContextBuilder
from continuous_claude.runner.loop import Runner
from continuous_claude.ledger import Ledger, Learning, LearningCategory


class TestIterationLimit:
    """Tests for IterationLimit stop condition."""

    def test_should_stop_before_limit(self):
        """Should not stop when iterations are below limit."""
        condition = IterationLimit(max_iterations=5)

        should_stop, reason = condition.should_stop(iteration=3, state={})

        assert should_stop is False
        assert reason == ""

    def test_should_stop_at_limit(self):
        """Should stop when iterations reach the limit."""
        condition = IterationLimit(max_iterations=5)

        should_stop, reason = condition.should_stop(iteration=5, state={})

        assert should_stop is True
        assert "5" in reason
        assert "maximum iterations" in reason.lower()

    def test_should_stop_above_limit(self):
        """Should stop when iterations exceed the limit."""
        condition = IterationLimit(max_iterations=5)

        should_stop, reason = condition.should_stop(iteration=7, state={})

        assert should_stop is True

    def test_reset_is_noop(self):
        """Reset should be a no-op for IterationLimit."""
        condition = IterationLimit(max_iterations=5)

        # Should not raise
        condition.reset()


class TestCostLimit:
    """Tests for CostLimit stop condition."""

    def test_should_not_stop_under_budget(self):
        """Should not stop when cost is under budget."""
        condition = CostLimit(max_cost_usd=10.0)

        should_stop, reason = condition.should_stop(
            iteration=1,
            state={"total_cost": 5.0}
        )

        assert should_stop is False
        assert reason == ""

    def test_should_stop_at_budget(self):
        """Should stop when cost reaches the budget."""
        condition = CostLimit(max_cost_usd=10.0)

        should_stop, reason = condition.should_stop(
            iteration=1,
            state={"total_cost": 10.0}
        )

        assert should_stop is True
        assert "cost" in reason.lower() or "budget" in reason.lower()

    def test_should_stop_over_budget(self):
        """Should stop when cost exceeds the budget."""
        condition = CostLimit(max_cost_usd=10.0)

        should_stop, reason = condition.should_stop(
            iteration=1,
            state={"total_cost": 15.0}
        )

        assert should_stop is True

    def test_missing_cost_in_state(self):
        """Should handle missing cost in state gracefully."""
        condition = CostLimit(max_cost_usd=10.0)

        should_stop, reason = condition.should_stop(
            iteration=1,
            state={}
        )

        assert should_stop is False

    def test_reset_clears_total_cost(self):
        """Reset should clear the tracked total cost."""
        condition = CostLimit(max_cost_usd=10.0)
        condition.total_cost = 5.0

        condition.reset()

        assert condition.total_cost == 0.0


class TestTimeLimit:
    """Tests for TimeLimit stop condition."""

    def test_should_not_stop_before_time_limit(self):
        """Should not stop when time limit has not been reached."""
        condition = TimeLimit(duration=timedelta(hours=1))

        # First call sets the start time
        should_stop, reason = condition.should_stop(iteration=1, state={})

        assert should_stop is False
        assert reason == ""

    def test_should_stop_after_time_limit(self):
        """Should stop when time limit has been exceeded."""
        condition = TimeLimit(duration=timedelta(seconds=1))
        # Set start time to the past
        condition.start_time = datetime.now(timezone.utc) - timedelta(seconds=10)

        should_stop, reason = condition.should_stop(iteration=1, state={})

        assert should_stop is True
        assert "time" in reason.lower()

    def test_initializes_start_time_on_first_call(self):
        """Should initialize start_time on first call if not set."""
        condition = TimeLimit(duration=timedelta(hours=1))

        assert condition.start_time is None

        condition.should_stop(iteration=1, state={})

        assert condition.start_time is not None

    def test_reset_clears_start_time(self):
        """Reset should clear the start time."""
        condition = TimeLimit(duration=timedelta(hours=1))
        condition.start_time = datetime.now(timezone.utc)

        condition.reset()

        assert condition.start_time is None


class TestNoNewLearnings:
    """Tests for NoNewLearnings (stale iterations) stop condition."""

    def test_should_not_stop_when_learnings_increase(self):
        """Should not stop when new learnings are being produced."""
        condition = NoNewLearnings(max_stale_iterations=3)

        # First check
        should_stop, _ = condition.should_stop(iteration=1, state={"total_learnings": 5})
        assert should_stop is False

        # Second check with more learnings
        should_stop, _ = condition.should_stop(iteration=2, state={"total_learnings": 8})
        assert should_stop is False

    def test_should_stop_after_stale_iterations(self):
        """Should stop after max stale iterations with no new learnings."""
        condition = NoNewLearnings(max_stale_iterations=3)

        # Initial learning count
        condition.should_stop(iteration=1, state={"total_learnings": 5})

        # Three stale iterations
        condition.should_stop(iteration=2, state={"total_learnings": 5})
        condition.should_stop(iteration=3, state={"total_learnings": 5})
        should_stop, reason = condition.should_stop(iteration=4, state={"total_learnings": 5})

        assert should_stop is True
        assert "no new learnings" in reason.lower()

    def test_stale_counter_resets_on_new_learning(self):
        """Stale counter should reset when new learnings appear."""
        condition = NoNewLearnings(max_stale_iterations=3)

        # Initial
        condition.should_stop(iteration=1, state={"total_learnings": 5})

        # Two stale iterations
        condition.should_stop(iteration=2, state={"total_learnings": 5})
        condition.should_stop(iteration=3, state={"total_learnings": 5})

        # New learning resets counter
        condition.should_stop(iteration=4, state={"total_learnings": 6})

        # Should not stop immediately after
        should_stop, _ = condition.should_stop(iteration=5, state={"total_learnings": 6})
        assert should_stop is False

    def test_reset_clears_counters(self):
        """Reset should clear all tracking state."""
        condition = NoNewLearnings(max_stale_iterations=3)
        condition.stale_count = 2
        condition.last_learning_count = 10

        condition.reset()

        assert condition.stale_count == 0
        assert condition.last_learning_count == 0


class TestCompositeStopCondition:
    """Tests for CompositeStopCondition (any condition logic)."""

    def test_should_not_stop_when_no_conditions_met(self):
        """Should not stop when no conditions are met."""
        condition = CompositeStopCondition([
            IterationLimit(max_iterations=10),
            CostLimit(max_cost_usd=100.0),
        ])

        should_stop, reason = condition.should_stop(
            iteration=1,
            state={"total_cost": 5.0}
        )

        assert should_stop is False
        assert reason == ""

    def test_should_stop_when_any_condition_met(self):
        """Should stop when any single condition is met."""
        condition = CompositeStopCondition([
            IterationLimit(max_iterations=5),
            CostLimit(max_cost_usd=100.0),
        ])

        # Iteration limit is met, cost is not
        should_stop, reason = condition.should_stop(
            iteration=5,
            state={"total_cost": 5.0}
        )

        assert should_stop is True
        assert "iterations" in reason.lower()

    def test_should_stop_with_cost_condition_met(self):
        """Should stop when cost condition is met."""
        condition = CompositeStopCondition([
            IterationLimit(max_iterations=10),
            CostLimit(max_cost_usd=10.0),
        ])

        # Cost limit is met, iteration is not
        should_stop, reason = condition.should_stop(
            iteration=2,
            state={"total_cost": 15.0}
        )

        assert should_stop is True
        assert "cost" in reason.lower() or "budget" in reason.lower()

    def test_reset_resets_all_conditions(self):
        """Reset should reset all child conditions."""
        time_condition = TimeLimit(duration=timedelta(hours=1))
        time_condition.start_time = datetime.now(timezone.utc)

        cost_condition = CostLimit(max_cost_usd=100.0)
        cost_condition.total_cost = 50.0

        condition = CompositeStopCondition([time_condition, cost_condition])

        condition.reset()

        assert time_condition.start_time is None
        assert cost_condition.total_cost == 0.0

    def test_empty_conditions_list_never_stops(self):
        """Should never stop with an empty conditions list."""
        condition = CompositeStopCondition([])

        should_stop, reason = condition.should_stop(
            iteration=1000,
            state={"total_cost": 10000.0}
        )

        assert should_stop is False

    def test_first_matching_condition_reason_returned(self):
        """Should return the reason from the first matching condition."""
        condition = CompositeStopCondition([
            IterationLimit(max_iterations=5),
            CostLimit(max_cost_usd=1.0),  # Also met
        ])

        should_stop, reason = condition.should_stop(
            iteration=5,
            state={"total_cost": 10.0}
        )

        assert should_stop is True
        # First condition (iteration) should be reported
        assert "iterations" in reason.lower()


class TestConfidenceThreshold:
    """Tests for ConfidenceThreshold stop condition."""

    def test_should_not_stop_when_threshold_not_reached(self, ledger_path):
        """Should not stop when target learning is below threshold."""
        ledger = Ledger(ledger_path)

        learning = Learning(
            category=LearningCategory.DISCOVERY,
            content="Target learning about authentication",
            confidence=0.5,
        )
        ledger.append_block(
            session_id="test-session",
            learnings=[learning],
            deduplicate=False,
        )

        condition = ConfidenceThreshold(
            ledger=ledger,
            target_content="authentication",
            threshold=0.9,
        )

        should_stop, reason = condition.should_stop(iteration=1, state={})

        assert should_stop is False

    def test_should_stop_when_threshold_reached(self, ledger_path):
        """Should stop when target learning reaches confidence threshold."""
        ledger = Ledger(ledger_path)

        learning = Learning(
            category=LearningCategory.DISCOVERY,
            content="Target learning about authentication patterns",
            confidence=0.95,
        )
        ledger.append_block(
            session_id="test-session",
            learnings=[learning],
            deduplicate=False,
        )

        condition = ConfidenceThreshold(
            ledger=ledger,
            target_content="authentication",
            threshold=0.9,
        )

        should_stop, reason = condition.should_stop(iteration=1, state={})

        assert should_stop is True
        assert "confidence" in reason.lower()

    def test_case_insensitive_content_match(self, ledger_path):
        """Should match target content case-insensitively."""
        ledger = Ledger(ledger_path)

        learning = Learning(
            category=LearningCategory.PATTERN,
            content="Use DEPENDENCY INJECTION for services",
            confidence=0.95,
        )
        ledger.append_block(
            session_id="test-session",
            learnings=[learning],
            deduplicate=False,
        )

        condition = ConfidenceThreshold(
            ledger=ledger,
            target_content="Dependency Injection",
            threshold=0.9,
        )

        should_stop, reason = condition.should_stop(iteration=1, state={})

        assert should_stop is True


class TestContextBuilder:
    """Tests for ContextBuilder."""

    def test_initialization_with_both_ledgers(self, ledger_path, temp_dir):
        """Should initialize with both project and global ledgers."""
        project_ledger = Ledger(ledger_path)
        global_ledger_path = temp_dir / "global_ledger"
        global_ledger_path.mkdir()
        global_ledger = Ledger(global_ledger_path)

        builder = ContextBuilder(
            project_ledger=project_ledger,
            global_ledger=global_ledger,
        )

        assert builder.project_ledger is project_ledger
        assert builder.global_ledger is global_ledger

    def test_initialization_with_no_ledgers(self):
        """Should initialize with no ledgers."""
        builder = ContextBuilder()

        assert builder.project_ledger is None
        assert builder.global_ledger is None

    def test_detect_project_type_python(self, temp_dir):
        """Should detect Python projects by pyproject.toml."""
        (temp_dir / "pyproject.toml").touch()

        builder = ContextBuilder()
        result = builder.detect_project_type(temp_dir)

        assert result["type"] == "python"
        assert result["package_manager"] == "uv"
        assert "test" in result["commands"]
        assert "pytest" in result["commands"]["test"]

    def test_detect_project_type_node_bun(self, temp_dir):
        """Should detect Node.js with bun projects."""
        (temp_dir / "package.json").touch()
        (temp_dir / "bun.lockb").touch()

        builder = ContextBuilder()
        result = builder.detect_project_type(temp_dir)

        assert result["type"] == "node"
        assert result["package_manager"] == "bun"
        assert "test" in result["commands"]
        assert "bun" in result["commands"]["test"]

    def test_detect_project_type_node_npm(self, temp_dir):
        """Should detect Node.js with npm projects (no bun.lockb)."""
        (temp_dir / "package.json").touch()

        builder = ContextBuilder()
        result = builder.detect_project_type(temp_dir)

        assert result["type"] == "node"
        assert result["package_manager"] == "npm"
        assert "test" in result["commands"]
        assert "npm" in result["commands"]["test"]

    def test_detect_project_type_unknown(self, temp_dir):
        """Should return unknown for unrecognized project types."""
        builder = ContextBuilder()
        result = builder.detect_project_type(temp_dir)

        assert result["type"] == "unknown"
        assert result["package_manager"] is None

    def test_build_knowledge_context_empty_ledger(self, ledger_path):
        """Should return empty string for empty ledger."""
        ledger = Ledger(ledger_path)
        builder = ContextBuilder(project_ledger=ledger)

        context = builder.build_knowledge_context()

        assert context == ""

    def test_build_knowledge_context_with_learnings(self, ledger_path):
        """Should include learnings in context."""
        ledger = Ledger(ledger_path)
        learning = Learning(
            category=LearningCategory.DISCOVERY,
            content="Test discovery about the system",
            confidence=0.8,
        )
        ledger.append_block(
            session_id="test-session",
            learnings=[learning],
            deduplicate=False,
        )

        builder = ContextBuilder(project_ledger=ledger)
        context = builder.build_knowledge_context(min_confidence=0.5)

        assert "Prior Knowledge" in context
        assert "Test discovery about the system" in context
        assert "discovery" in context.lower()

    def test_build_knowledge_context_filters_by_confidence(self, ledger_path):
        """Should filter learnings by minimum confidence."""
        ledger = Ledger(ledger_path)

        high_confidence = Learning(
            category=LearningCategory.PATTERN,
            content="High confidence pattern",
            confidence=0.9,
        )
        low_confidence = Learning(
            category=LearningCategory.DISCOVERY,
            content="Low confidence discovery",
            confidence=0.3,
        )

        ledger.append_block(
            session_id="test-session",
            learnings=[high_confidence, low_confidence],
            deduplicate=False,
        )

        builder = ContextBuilder(project_ledger=ledger)
        context = builder.build_knowledge_context(min_confidence=0.7)

        assert "High confidence pattern" in context
        assert "Low confidence discovery" not in context

    def test_build_project_context_includes_commands(self, temp_dir):
        """Should include project commands in context."""
        (temp_dir / "pyproject.toml").touch()

        builder = ContextBuilder()
        context = builder.build_project_context(temp_dir)

        assert "Project Environment" in context
        assert "python" in context
        assert "uv" in context

    def test_build_project_context_unknown_returns_empty(self, temp_dir):
        """Should return empty string for unknown project types."""
        builder = ContextBuilder()
        context = builder.build_project_context(temp_dir)

        assert context == ""

    def test_build_full_context_includes_all_parts(self, ledger_path, temp_dir):
        """Should build complete context with all components."""
        # Create Python project
        (temp_dir / "pyproject.toml").touch()

        ledger = Ledger(ledger_path)
        learning = Learning(
            category=LearningCategory.PATTERN,
            content="Useful pattern for testing",
            confidence=0.8,
        )
        ledger.append_block(
            session_id="test-session",
            learnings=[learning],
            deduplicate=False,
        )

        builder = ContextBuilder(project_ledger=ledger)
        context = builder.build_full_context(
            project_path=temp_dir,
            user_prompt="Implement the feature",
            min_confidence=0.5,
        )

        assert "Project Environment" in context
        assert "Prior Knowledge" in context
        assert "Task" in context
        assert "Implement the feature" in context

    def test_build_full_context_with_only_task(self, temp_dir):
        """Should include just task when no project info or learnings."""
        builder = ContextBuilder()
        context = builder.build_full_context(
            project_path=temp_dir,
            user_prompt="Do something",
        )

        assert "Task" in context
        assert "Do something" in context


class TestRunnerInitialization:
    """Tests for Runner initialization."""

    def test_default_stop_condition(self, project_dir, ledger_path):
        """Should use default IterationLimit(10) when no conditions provided."""
        ledger = Ledger(ledger_path)
        runner = Runner(
            project_path=project_dir,
            project_ledger=ledger,
        )

        # Default is CompositeStopCondition with IterationLimit(10)
        assert isinstance(runner.stop_condition, CompositeStopCondition)
        assert len(runner.stop_condition.conditions) == 1
        assert isinstance(runner.stop_condition.conditions[0], IterationLimit)
        assert runner.stop_condition.conditions[0].max_iterations == 10

    def test_custom_stop_conditions(self, project_dir, ledger_path):
        """Should use provided stop conditions."""
        ledger = Ledger(ledger_path)
        conditions = [
            IterationLimit(5),
            CostLimit(10.0),
        ]

        runner = Runner(
            project_path=project_dir,
            project_ledger=ledger,
            stop_conditions=conditions,
        )

        assert len(runner.stop_condition.conditions) == 2

    def test_paths_resolved(self, project_dir, ledger_path):
        """Should store project path correctly."""
        ledger = Ledger(ledger_path)

        runner = Runner(
            project_path=project_dir,
            project_ledger=ledger,
        )

        assert runner.project_path == project_dir

    def test_initial_state(self, project_dir, ledger_path):
        """Should initialize state with correct default values."""
        ledger = Ledger(ledger_path)

        runner = Runner(
            project_path=project_dir,
            project_ledger=ledger,
        )

        assert runner.state["iteration"] == 0
        assert runner.state["total_cost"] == 0.0
        assert runner.state["total_learnings"] == 0
        assert runner.state["start_time"] is None
        assert "session_id" in runner.state

    def test_context_builder_initialized(self, project_dir, ledger_path, temp_dir):
        """Should initialize context builder with both ledgers."""
        project_ledger = Ledger(ledger_path)
        global_ledger_path = temp_dir / "global_ledger"
        global_ledger_path.mkdir()
        global_ledger = Ledger(global_ledger_path)

        runner = Runner(
            project_path=project_dir,
            project_ledger=project_ledger,
            global_ledger=global_ledger,
        )

        assert runner.context_builder.project_ledger is project_ledger
        assert runner.context_builder.global_ledger is global_ledger


class TestRunnerLearningExtraction:
    """Tests for Runner._extract_learnings method."""

    def test_extract_discovery_learning(self, project_dir, ledger_path):
        """Should extract DISCOVERY tagged learnings."""
        ledger = Ledger(ledger_path)
        runner = Runner(project_path=project_dir, project_ledger=ledger)

        output = "[DISCOVERY] The API uses JWT tokens for authentication"
        learnings = runner._extract_learnings(output)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.DISCOVERY
        assert "JWT tokens" in learnings[0].content

    def test_extract_decision_learning(self, project_dir, ledger_path):
        """Should extract DECISION tagged learnings."""
        ledger = Ledger(ledger_path)
        runner = Runner(project_path=project_dir, project_ledger=ledger)

        output = "[DECISION] Using repository pattern for data access"
        learnings = runner._extract_learnings(output)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.DECISION
        assert "repository pattern" in learnings[0].content

    def test_extract_error_learning(self, project_dir, ledger_path):
        """Should extract ERROR tagged learnings."""
        ledger = Ledger(ledger_path)
        runner = Runner(project_path=project_dir, project_ledger=ledger)

        output = "[ERROR] Do not use raw SQL queries to avoid injection"
        learnings = runner._extract_learnings(output)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.ERROR
        assert "SQL queries" in learnings[0].content

    def test_extract_pattern_learning(self, project_dir, ledger_path):
        """Should extract PATTERN tagged learnings."""
        ledger = Ledger(ledger_path)
        runner = Runner(project_path=project_dir, project_ledger=ledger)

        output = "[PATTERN] All API routes follow /api/v1/resource/action"
        learnings = runner._extract_learnings(output)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.PATTERN
        assert "API routes" in learnings[0].content

    def test_extract_multiple_learnings(self, project_dir, ledger_path):
        """Should extract multiple learnings from output."""
        ledger = Ledger(ledger_path)
        runner = Runner(project_path=project_dir, project_ledger=ledger)

        output = """
        [DISCOVERY] Found that the auth module uses OAuth2
        [DECISION] Will use async handlers for better performance
        [PATTERN] Controllers use dependency injection
        """
        learnings = runner._extract_learnings(output)

        assert len(learnings) == 3
        categories = {l.category for l in learnings}
        assert LearningCategory.DISCOVERY in categories
        assert LearningCategory.DECISION in categories
        assert LearningCategory.PATTERN in categories

    def test_extract_no_learnings(self, project_dir, ledger_path):
        """Should return empty list when no learning tags present."""
        ledger = Ledger(ledger_path)
        runner = Runner(project_path=project_dir, project_ledger=ledger)

        output = "I completed the task successfully without any notable insights."
        learnings = runner._extract_learnings(output)

        assert len(learnings) == 0

    def test_extract_case_insensitive(self, project_dir, ledger_path):
        """Should handle case-insensitive tags."""
        ledger = Ledger(ledger_path)
        runner = Runner(project_path=project_dir, project_ledger=ledger)

        output = "[discovery] This is a case insensitive discovery"
        learnings = runner._extract_learnings(output)

        assert len(learnings) == 1
        assert learnings[0].category == LearningCategory.DISCOVERY


class TestRunnerPromptInjection:
    """Tests for Runner prompt injection methods."""

    def test_inject_extraction_prompt(self, project_dir, ledger_path):
        """Should add extraction instructions to prompt."""
        ledger = Ledger(ledger_path)
        runner = Runner(project_path=project_dir, project_ledger=ledger)

        base_prompt = "Implement the feature"
        result = runner._inject_extraction_prompt(base_prompt)

        assert "Implement the feature" in result
        assert "[DISCOVERY]" in result
        assert "[DECISION]" in result
        assert "[ERROR]" in result
        assert "[PATTERN]" in result

    def test_inject_autonomy_prompt(self, project_dir, ledger_path):
        """Should add autonomy instructions to prompt."""
        ledger = Ledger(ledger_path)
        runner = Runner(project_path=project_dir, project_ledger=ledger)

        base_prompt = "Work on the task"
        result = runner._inject_autonomy_prompt(base_prompt)

        assert "Work on the task" in result
        assert "autonomous" in result.lower()
        assert "continue" in result.lower()


class TestRunnerClaudeExecution:
    """Tests for Runner._run_claude method (mocked)."""

    @patch("continuous_claude.runner.loop.subprocess.run")
    def test_run_claude_success(self, mock_run, project_dir, ledger_path):
        """Should handle successful Claude CLI execution."""
        ledger = Ledger(ledger_path)
        runner = Runner(project_path=project_dir, project_ledger=ledger)

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "result": "Task completed successfully",
                "cost_usd": 0.05,
                "session_id": "test-session",
            }),
            stderr="",
        )

        result = runner._run_claude("Test prompt")

        assert result["success"] is True
        assert "Task completed" in result["output"]
        assert result["cost"] == 0.05

    @patch("continuous_claude.runner.loop.subprocess.run")
    def test_run_claude_failure(self, mock_run, project_dir, ledger_path):
        """Should handle Claude CLI failure."""
        ledger = Ledger(ledger_path)
        runner = Runner(project_path=project_dir, project_ledger=ledger)

        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Error: API rate limit exceeded",
        )

        result = runner._run_claude("Test prompt")

        assert result["success"] is False
        assert "rate limit" in result["output"].lower()
        assert result["cost"] == 0.0

    @patch("continuous_claude.runner.loop.subprocess.run")
    def test_run_claude_timeout(self, mock_run, project_dir, ledger_path):
        """Should handle timeout during Claude CLI execution."""
        import subprocess

        ledger = Ledger(ledger_path)
        runner = Runner(project_path=project_dir, project_ledger=ledger)

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=600)

        result = runner._run_claude("Test prompt")

        assert result["success"] is False
        assert "timeout" in result["output"].lower()

    @patch("continuous_claude.runner.loop.subprocess.run")
    def test_run_claude_json_decode_error(self, mock_run, project_dir, ledger_path):
        """Should handle non-JSON output from Claude CLI."""
        ledger = Ledger(ledger_path)
        runner = Runner(project_path=project_dir, project_ledger=ledger)

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Raw text output without JSON",
            stderr="",
        )

        result = runner._run_claude("Test prompt")

        assert result["success"] is True
        assert result["output"] == "Raw text output without JSON"
        assert result["cost"] == 0.0


class TestRunnerRun:
    """Tests for Runner.run method (integration-like tests with mocks)."""

    @patch("continuous_claude.runner.loop.subprocess.run")
    @patch("continuous_claude.runner.loop.console")
    def test_run_stops_at_iteration_limit(self, mock_console, mock_run, project_dir, ledger_path):
        """Should stop when iteration limit is reached."""
        ledger = Ledger(ledger_path)
        runner = Runner(
            project_path=project_dir,
            project_ledger=ledger,
            stop_conditions=[IterationLimit(2)],
        )

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"result": "Done", "cost_usd": 0.01}),
            stderr="",
        )

        result = runner.run("Test task")

        assert result["iterations"] == 2

    @patch("continuous_claude.runner.loop.subprocess.run")
    @patch("continuous_claude.runner.loop.console")
    def test_run_extracts_and_stores_learnings(self, mock_console, mock_run, project_dir, ledger_path):
        """Should extract learnings and store them in ledger."""
        ledger = Ledger(ledger_path)
        runner = Runner(
            project_path=project_dir,
            project_ledger=ledger,
            stop_conditions=[IterationLimit(1)],
        )

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({
                "result": "[DISCOVERY] Important insight about the codebase",
                "cost_usd": 0.01,
            }),
            stderr="",
        )

        result = runner.run("Test task")

        assert result["learnings"] >= 1
        blocks = ledger.get_all_blocks()
        assert len(blocks) >= 1

    @patch("continuous_claude.runner.loop.subprocess.run")
    @patch("continuous_claude.runner.loop.console")
    def test_run_accumulates_cost(self, mock_console, mock_run, project_dir, ledger_path):
        """Should accumulate cost across iterations."""
        ledger = Ledger(ledger_path)
        runner = Runner(
            project_path=project_dir,
            project_ledger=ledger,
            stop_conditions=[IterationLimit(3)],
        )

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"result": "Done", "cost_usd": 0.10}),
            stderr="",
        )

        result = runner.run("Test task")

        # 3 iterations * $0.10 each = $0.30
        assert result["cost"] == pytest.approx(0.30, abs=0.01)

    @patch("continuous_claude.runner.loop.subprocess.run")
    @patch("continuous_claude.runner.loop.console")
    def test_run_continues_on_failed_iteration(self, mock_console, mock_run, project_dir, ledger_path):
        """Should continue to next iteration when one fails."""
        ledger = Ledger(ledger_path)
        runner = Runner(
            project_path=project_dir,
            project_ledger=ledger,
            stop_conditions=[IterationLimit(3)],
        )

        # First call fails, second succeeds
        mock_run.side_effect = [
            MagicMock(returncode=1, stdout="", stderr="Error"),
            MagicMock(returncode=0, stdout=json.dumps({"result": "OK", "cost_usd": 0.01}), stderr=""),
            MagicMock(returncode=0, stdout=json.dumps({"result": "OK", "cost_usd": 0.01}), stderr=""),
        ]

        result = runner.run("Test task")

        assert result["iterations"] == 3

    @patch("continuous_claude.runner.loop.subprocess.run")
    @patch("continuous_claude.runner.loop.console")
    def test_run_records_session_id(self, mock_console, mock_run, project_dir, ledger_path):
        """Should include session_id in result."""
        ledger = Ledger(ledger_path)
        runner = Runner(
            project_path=project_dir,
            project_ledger=ledger,
            stop_conditions=[IterationLimit(1)],
        )

        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({"result": "Done", "cost_usd": 0.01}),
            stderr="",
        )

        result = runner.run("Test task")

        assert "session_id" in result
        assert len(result["session_id"]) > 0
