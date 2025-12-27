"""Main execution loop for continuous Claude sessions."""

import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional
from uuid import uuid4

from rich.console import Console
from rich.panel import Panel

from ..ledger import Ledger, Learning, LearningCategory
from .context import ContextBuilder
from .stop_conditions import StopCondition, CompositeStopCondition, IterationLimit


console = Console()


class Runner:
    """Manages the continuous execution loop for Claude sessions."""

    def __init__(
        self,
        project_path: Path,
        project_ledger: Ledger,
        global_ledger: Optional[Ledger] = None,
        stop_conditions: Optional[list[StopCondition]] = None,
    ):
        """Initialize the runner.

        Args:
            project_path: Path to the project directory
            project_ledger: Project-specific ledger
            global_ledger: Global ledger for cross-project knowledge
            stop_conditions: List of conditions that trigger stopping
        """
        self.project_path = project_path
        self.project_ledger = project_ledger
        self.global_ledger = global_ledger
        self.context_builder = ContextBuilder(project_ledger, global_ledger)

        # Default stop condition: 10 iterations
        if stop_conditions is None:
            stop_conditions = [IterationLimit(10)]

        self.stop_condition = CompositeStopCondition(stop_conditions)

        self.state = {
            "iteration": 0,
            "total_cost": 0.0,
            "total_learnings": 0,
            "session_id": str(uuid4()),
            "start_time": None,
        }

    def _run_claude(self, prompt: str) -> dict:
        """Execute Claude CLI with the given prompt.

        Args:
            prompt: The prompt to send to Claude

        Returns:
            Dict with output, cost, and session info
        """
        # Write prompt to temp file for complex prompts
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False) as f:
            f.write(prompt)
            prompt_file = f.name

        try:
            # Run Claude CLI
            # Using --print to get just the output, --output-format json for structured response
            result = subprocess.run(
                [
                    "claude",
                    "--print",
                    "--output-format", "json",
                    "--prompt-file", prompt_file,
                ],
                cwd=self.project_path,
                capture_output=True,
                text=True,
                timeout=600,  # 10 minute timeout per iteration
            )

            if result.returncode != 0:
                console.print(f"[red]Claude CLI error:[/red] {result.stderr}")
                return {
                    "success": False,
                    "output": result.stderr,
                    "cost": 0.0,
                }

            # Parse JSON output
            try:
                output = json.loads(result.stdout)
                return {
                    "success": True,
                    "output": output.get("result", result.stdout),
                    "cost": output.get("cost_usd", 0.0),
                    "session_id": output.get("session_id", ""),
                }
            except json.JSONDecodeError:
                # Fallback to raw output
                return {
                    "success": True,
                    "output": result.stdout,
                    "cost": 0.0,
                }

        except subprocess.TimeoutExpired:
            console.print("[yellow]Claude CLI timed out[/yellow]")
            return {
                "success": False,
                "output": "Timeout",
                "cost": 0.0,
            }
        finally:
            Path(prompt_file).unlink(missing_ok=True)

    def _extract_learnings(self, output: str) -> list[Learning]:
        """Extract learnings from Claude's output.

        Args:
            output: Claude's response text

        Returns:
            List of extracted learnings
        """
        learnings = []

        # Look for structured learning markers in output
        # Format: [LEARNING:category] content
        # Or: [DISCOVERY] content, [DECISION] content, etc.

        import re

        patterns = {
            LearningCategory.DISCOVERY: r"\[DISCOVERY\]\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
            LearningCategory.DECISION: r"\[DECISION\]\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
            LearningCategory.ERROR: r"\[ERROR\]\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
            LearningCategory.PATTERN: r"\[PATTERN\]\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
        }

        for category, pattern in patterns.items():
            matches = re.findall(pattern, output, re.DOTALL | re.IGNORECASE)
            for match in matches:
                content = match.strip()
                if content:
                    learning = Learning(
                        category=category,
                        content=content,
                        confidence=0.5,  # Start at neutral confidence
                    )
                    learnings.append(learning)

        return learnings

    def _inject_extraction_prompt(self, base_prompt: str) -> str:
        """Add instructions for Claude to output structured learnings.

        Args:
            base_prompt: The original prompt

        Returns:
            Prompt with extraction instructions
        """
        extraction_instructions = """

## Output Format

As you work, document any significant insights using these tags:

- [DISCOVERY] - New information learned about the codebase, APIs, or patterns
- [DECISION] - Architectural choices or tradeoffs you're making
- [ERROR] - Mistakes to avoid or gotchas discovered
- [PATTERN] - Reusable solutions or conventions identified

Example:
[DISCOVERY] The authentication middleware uses JWT tokens stored in httpOnly cookies
[DECISION] Using repository pattern for database access to enable easier testing
[ERROR] Don't use raw SQL queries - always use the ORM to prevent injection
[PATTERN] All API routes follow /api/v1/<resource>/<action> convention
"""
        return base_prompt + extraction_instructions

    def _inject_autonomy_prompt(self, base_prompt: str) -> str:
        """Add explicit instructions for autonomous continuation.

        Args:
            base_prompt: The original prompt

        Returns:
            Prompt with autonomy instructions
        """
        autonomy_instructions = """

## Autonomous Operation Mode

You are operating in autonomous continuous mode. Follow these critical instructions:

1. **Continue working through the entire plan without waiting for user confirmation.**
   Do not pause after each step to ask if you should continue. Proceed autonomously.

2. **Only stop when blocked, not when completing intermediate steps.**
   Completing a subtask is not a stopping point. Only stop if you encounter:
   - An unrecoverable error that requires user input
   - A decision that fundamentally changes the project direction
   - Missing credentials, permissions, or external resources you cannot obtain

3. **If you complete one task, immediately proceed to the next.**
   After finishing any step, immediately move to the next item in your plan.
   Do not summarize progress and wait - keep working.

4. **Use the TodoWrite tool to track remaining work.**
   Maintain an active todo list showing:
   - Current task (in_progress)
   - Remaining tasks (pending)
   - Completed tasks (completed)
   Update the todo list as you progress.

5. **Maximize progress per iteration.**
   Each response should accomplish as much as possible. Batch related operations.
   Use parallel tool calls when tasks are independent.

6. **Be self-directed.**
   If the plan is ambiguous, make reasonable assumptions and document them.
   Prefer action over asking clarifying questions for minor details.
"""
        return base_prompt + autonomy_instructions

    def run(self, initial_prompt: str) -> dict:
        """Run the continuous execution loop.

        Args:
            initial_prompt: The initial task prompt

        Returns:
            Summary of the run
        """
        self.state["start_time"] = datetime.utcnow()
        self.stop_condition.reset()

        console.print(Panel(
            f"Starting continuous Claude session\n"
            f"Project: {self.project_path}\n"
            f"Session: {self.state['session_id']}",
            title="Continuous Claude",
        ))

        while True:
            iteration = self.state["iteration"]

            # Check stop conditions
            should_stop, reason = self.stop_condition.should_stop(iteration, self.state)
            if should_stop:
                console.print(f"\n[yellow]Stopping:[/yellow] {reason}")
                break

            console.print(f"\n[bold blue]Iteration {iteration + 1}[/bold blue]")

            # Build context with prior knowledge
            context = self.context_builder.build_full_context(
                self.project_path,
                initial_prompt,
                min_confidence=0.5,
            )

            # Add autonomy and extraction prompts
            prompt_with_autonomy = self._inject_autonomy_prompt(context)
            full_prompt = self._inject_extraction_prompt(prompt_with_autonomy)

            # Run Claude
            result = self._run_claude(full_prompt)

            if not result["success"]:
                console.print(f"[red]Iteration failed[/red]")
                self.state["iteration"] += 1
                continue

            # Update cost tracking
            self.state["total_cost"] += result.get("cost", 0.0)

            # Extract learnings
            learnings = self._extract_learnings(result["output"])

            if learnings:
                console.print(f"[green]Extracted {len(learnings)} learnings[/green]")

                # Save to ledger
                block = self.project_ledger.append_block(
                    session_id=self.state["session_id"],
                    learnings=learnings,
                )
                console.print(f"[dim]Block {block.id} added to ledger[/dim]")

                self.state["total_learnings"] += len(learnings)
            else:
                console.print("[dim]No new learnings extracted[/dim]")

            self.state["iteration"] += 1

        # Final summary
        duration = datetime.utcnow() - self.state["start_time"]
        console.print(Panel(
            f"Iterations: {self.state['iteration']}\n"
            f"Total learnings: {self.state['total_learnings']}\n"
            f"Total cost: ${self.state['total_cost']:.4f}\n"
            f"Duration: {duration}",
            title="Run Complete",
        ))

        return {
            "iterations": self.state["iteration"],
            "learnings": self.state["total_learnings"],
            "cost": self.state["total_cost"],
            "duration": str(duration),
            "session_id": self.state["session_id"],
        }
