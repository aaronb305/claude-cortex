#!/usr/bin/env python3
"""
SubagentStop hook for claude-cortex.

Tracks agent deployments and their effectiveness when subagents (Task tool calls)
finish. This enables:
1. Logging agent usage patterns for analysis
2. Extracting learnings from agent outputs
3. Updating handoff with agent completion info
4. Tracking agent effectiveness metrics

The SubagentStop hook fires whenever a subagent created via the Task tool finishes.
It works similarly to the Stop hook but specifically for subagent completion events.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Ensure shared module is importable regardless of cwd
sys.path.insert(0, str(Path(__file__).parent))

from shared import (
    extract_learnings,
    file_lock,
    read_json,
    write_json,
)


# Agent name detection patterns
AGENT_PATTERNS = [
    # Common agent naming conventions from the project
    (r"code-implementer", "code-implementer"),
    (r"test-writer", "test-writer"),
    (r"research-agent", "research-agent"),
    (r"refactorer", "refactorer"),
    (r"bug-investigator", "bug-investigator"),
    (r"doc-writer", "doc-writer"),
    (r"continuous-runner", "continuous-runner"),
    (r"knowledge-retriever", "knowledge-retriever"),
    (r"learning-extractor", "learning-extractor"),
    (r"session-continuity", "session-continuity"),
    (r"outcome-tracker", "outcome-tracker"),
    (r"task-orchestrator", "task-orchestrator"),
    # Generic agent task patterns
    (r"implement|write\s+code|coding", "implementation-agent"),
    (r"test|testing|spec", "testing-agent"),
    (r"research|investigate|explore", "research-agent"),
    (r"refactor|clean\s*up|restructure", "refactoring-agent"),
    (r"debug|fix|bug", "debugging-agent"),
    (r"document|readme|docs", "documentation-agent"),
]


def get_agent_usage_path(cwd: str) -> Path:
    """Get path to the agent usage tracking file.

    Args:
        cwd: Current working directory.

    Returns:
        Path to agent_usage.json
    """
    project_dir = Path(cwd) if cwd else Path.cwd()
    claude_dir = project_dir / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    return claude_dir / "agent_usage.json"


def load_agent_usage(path: Path) -> dict:
    """Load existing agent usage data with file locking.

    Args:
        path: Path to agent_usage.json

    Returns:
        Agent usage data dictionary
    """
    try:
        if path.exists():
            with file_lock(path, exclusive=False):
                return read_json(path)
    except (json.JSONDecodeError, IOError):
        pass
    return {
        "total_deployments": 0,
        "agents": {},
        "sessions": {},
        "recent_deployments": [],
    }


def save_agent_usage(path: Path, data: dict) -> None:
    """Save agent usage data with file locking.

    Args:
        path: Path to agent_usage.json
        data: Agent usage data to save
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with file_lock(path, exclusive=True):
            write_json(path, data)
    except IOError:
        pass


def detect_agent_name(task_prompt: str, tool_input: dict) -> str:
    """Detect the agent name from the task prompt or tool input.

    Args:
        task_prompt: The prompt/task given to the subagent
        tool_input: The full tool input dictionary

    Returns:
        Detected agent name or "unknown-agent"
    """
    # First check if agent name is explicitly provided in tool_input
    if "agent" in tool_input:
        return tool_input["agent"]

    # Check for agent name patterns in the task prompt
    prompt_lower = task_prompt.lower() if task_prompt else ""

    for pattern, agent_name in AGENT_PATTERNS:
        if re.search(pattern, prompt_lower, re.IGNORECASE):
            return agent_name

    return "unknown-agent"


def extract_agent_output(input_data: dict) -> str:
    """Extract the text output from the subagent's response.

    Args:
        input_data: The hook input data

    Returns:
        Extracted text content from the agent's output
    """
    # The SubagentStop hook may receive message content similar to Stop hook
    message = input_data.get("message", {})

    if isinstance(message, str):
        return message

    if isinstance(message, dict):
        content = message.get("content", [])
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
                elif isinstance(item, str):
                    text_parts.append(item)
            return "\n".join(text_parts)

    # Check for tool_output field (alternative format)
    tool_output = input_data.get("tool_output", {})
    if isinstance(tool_output, str):
        return tool_output
    if isinstance(tool_output, dict):
        return tool_output.get("content", "") or tool_output.get("text", "")

    return ""


def estimate_effectiveness(output: str) -> str:
    """Estimate the effectiveness of the agent based on output patterns.

    Args:
        output: The agent's output text

    Returns:
        Effectiveness rating: "high", "medium", "low", or "unknown"
    """
    output_lower = output.lower()

    # High effectiveness indicators
    high_indicators = [
        "completed", "successfully", "done", "finished",
        "implemented", "created", "fixed", "resolved",
        "tests passing", "all tests pass",
    ]

    # Medium effectiveness indicators
    medium_indicators = [
        "partial", "some", "mostly", "almost",
        "with issues", "needs review", "requires",
    ]

    # Low effectiveness indicators
    low_indicators = [
        "failed", "error", "unable", "cannot",
        "blocked", "stuck", "not possible",
    ]

    high_count = sum(1 for ind in high_indicators if ind in output_lower)
    medium_count = sum(1 for ind in medium_indicators if ind in output_lower)
    low_count = sum(1 for ind in low_indicators if ind in output_lower)

    if high_count > medium_count + low_count:
        return "high"
    elif low_count > high_count + medium_count:
        return "low"
    elif medium_count > 0 or (high_count > 0 and low_count > 0):
        return "medium"
    else:
        return "unknown"


def log_agent_deployment(
    usage_data: dict,
    agent_name: str,
    session_id: str,
    task_prompt: str,
    output: str,
    effectiveness: str,
) -> None:
    """Log an agent deployment to the usage data.

    Args:
        usage_data: The agent usage data dictionary
        agent_name: Name of the deployed agent
        session_id: Current session ID
        task_prompt: The task given to the agent
        output: The agent's output
        effectiveness: Estimated effectiveness rating
    """
    timestamp = datetime.now(timezone.utc).isoformat()

    # Update total deployments
    usage_data["total_deployments"] = usage_data.get("total_deployments", 0) + 1

    # Update agent-specific stats
    if agent_name not in usage_data["agents"]:
        usage_data["agents"][agent_name] = {
            "deployment_count": 0,
            "effectiveness_counts": {"high": 0, "medium": 0, "low": 0, "unknown": 0},
            "last_deployed": None,
        }

    agent_stats = usage_data["agents"][agent_name]
    agent_stats["deployment_count"] += 1
    agent_stats["effectiveness_counts"][effectiveness] = (
        agent_stats["effectiveness_counts"].get(effectiveness, 0) + 1
    )
    agent_stats["last_deployed"] = timestamp

    # Update session stats
    if session_id not in usage_data.get("sessions", {}):
        usage_data["sessions"][session_id] = {
            "deployments": [],
            "started": timestamp,
        }

    usage_data["sessions"][session_id]["deployments"].append({
        "agent": agent_name,
        "timestamp": timestamp,
        "effectiveness": effectiveness,
        "task_preview": task_prompt[:100] if task_prompt else "",
    })

    # Add to recent deployments (keep last 20)
    recent = usage_data.get("recent_deployments", [])
    recent.insert(0, {
        "agent": agent_name,
        "session_id": session_id[:8] if session_id else "unknown",
        "timestamp": timestamp,
        "effectiveness": effectiveness,
        "task_preview": task_prompt[:50] if task_prompt else "",
    })
    usage_data["recent_deployments"] = recent[:20]


def extract_and_log_learnings(output: str, agent_name: str) -> list[dict]:
    """Extract learnings from agent output.

    Args:
        output: The agent's output text
        agent_name: Name of the agent (for source attribution)

    Returns:
        List of extracted learning dictionaries
    """
    learnings = extract_learnings(output)

    # Add agent source to learnings
    for learning in learnings:
        if not learning.get("source"):
            learning["source"] = f"agent:{agent_name}"

    return learnings


def update_handoff_with_agent_completion(
    cwd: str,
    agent_name: str,
    task_preview: str,
    effectiveness: str,
) -> None:
    """Update the current handoff with agent completion information.

    This adds agent completion info to the context notes of any ongoing handoff.

    Args:
        cwd: Current working directory
        agent_name: Name of the completed agent
        task_preview: Preview of the task that was completed
        effectiveness: Effectiveness rating
    """
    # This is a lightweight update - just log to stderr for now
    # A full implementation would update the handoff file
    print(
        f"[claude-cortex] Agent completed: {agent_name} "
        f"(effectiveness: {effectiveness})",
        file=sys.stderr,
    )


def main():
    """Main hook entry point."""
    try:
        input_data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)

    session_id = input_data.get("session_id", "")
    cwd = input_data.get("cwd", "")

    # Extract task information from tool_input
    tool_input = input_data.get("tool_input", {})
    task_prompt = tool_input.get("prompt", "") or tool_input.get("task", "")

    # Detect which agent was deployed
    agent_name = detect_agent_name(task_prompt, tool_input)

    # Extract agent output
    output = extract_agent_output(input_data)

    # Skip if we have no meaningful data
    if not output and not task_prompt:
        sys.exit(0)

    # Estimate effectiveness
    effectiveness = estimate_effectiveness(output)

    # Load and update agent usage tracking
    usage_path = get_agent_usage_path(cwd)
    usage_data = load_agent_usage(usage_path)

    log_agent_deployment(
        usage_data=usage_data,
        agent_name=agent_name,
        session_id=session_id,
        task_prompt=task_prompt,
        output=output,
        effectiveness=effectiveness,
    )

    # Save updated usage data
    save_agent_usage(usage_path, usage_data)

    # Extract learnings from agent output
    if output:
        learnings = extract_and_log_learnings(output, agent_name)
        if learnings:
            print(
                f"[claude-cortex] SubagentStop: Found {len(learnings)} "
                f"learnings from {agent_name}",
                file=sys.stderr,
            )
            # Note: Learnings are logged but not immediately stored to avoid
            # duplicating what session_end.py does. The learnings are captured
            # through the normal transcript-based extraction.

    # Update handoff context
    update_handoff_with_agent_completion(
        cwd=cwd,
        agent_name=agent_name,
        task_preview=task_prompt[:50] if task_prompt else "",
        effectiveness=effectiveness,
    )

    # Output for verbose mode
    print(
        f"[claude-cortex] SubagentStop: {agent_name} completed "
        f"(effectiveness: {effectiveness})",
        file=sys.stderr,
    )

    sys.exit(0)


if __name__ == "__main__":
    main()
