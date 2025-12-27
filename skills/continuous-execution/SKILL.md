---
name: continuous-execution
description: Run Claude in continuous autonomous mode with automatic learning extraction. Use when you need to run multiple iterations on a task via CLI, want uninterrupted progress on complex work, or the user says "run cclaude", "use the runner CLI", or "start continuous mode". **Complexity indicator**: CLI wrapper for the continuous execution loop. For full autonomous orchestration with agent-level decision making and multi-step workflows, use the `continuous-runner` agent instead.
allowed-tools: Bash, Read, Write
---

# Continuous Execution Skill

Run Claude in autonomous continuous mode, iterating through tasks with automatic learning extraction and configurable stop conditions.

## Quick Start

```bash
# Basic continuous run (10 iterations max)
uv run cclaude run "Implement user authentication"

# With project path
uv run cclaude run "Add validation" -p /path/to/project

# With custom limits
uv run cclaude run "Refactor auth module" \
  --max-iterations 20 \
  --max-cost 5.0 \
  --max-time 60 \
  --stale-threshold 3
```

## Command Options

```bash
uv run cclaude run <prompt> [options]

Options:
  -p, --project PATH       Project directory (default: current)
  --max-iterations INT     Maximum iterations (default: 10)
  --max-cost FLOAT         Maximum cost in USD
  --max-time INT           Maximum time in minutes
  --stale-threshold INT    Stop after N iterations without new learnings
```

## Stop Conditions

The runner stops when ANY of these conditions are met:

| Condition | Flag | Description |
|-----------|------|-------------|
| Iteration limit | `--max-iterations` | Maximum number of iterations |
| Cost limit | `--max-cost` | Maximum API cost in USD |
| Time limit | `--max-time` | Maximum execution time in minutes |
| Stale detection | `--stale-threshold` | N iterations without new learnings |

## What Happens During Execution

### Each Iteration

1. **Context Building**
   - Loads learnings from project + global ledgers
   - Injects autonomy instructions ("keep working, don't wait")
   - Adds learning extraction tags

2. **Execution**
   - Claude processes the prompt with full context
   - Works autonomously without waiting for confirmation
   - Uses TodoWrite to track progress

3. **Learning Extraction**
   - Scans output for `[DISCOVERY]`, `[DECISION]`, `[ERROR]`, `[PATTERN]` tags
   - Saves extracted learnings to project ledger
   - Updates search index

4. **State Update**
   - Tracks iteration count, cost, time
   - Checks stop conditions
   - Prepares for next iteration

### Autonomy Instructions

Each iteration includes explicit instructions:
- "Continue working through the entire plan without waiting for user confirmation"
- "Only stop when blocked, not when completing intermediate steps"
- "If you complete one task, immediately proceed to the next"
- "Use TodoWrite to track remaining work"

## Usage Patterns

### Feature Development
```bash
uv run cclaude run "Implement user registration with email verification" \
  --max-iterations 15 \
  --max-cost 3.0
```

### Refactoring
```bash
uv run cclaude run "Refactor auth module to use repository pattern" \
  --max-iterations 10 \
  --stale-threshold 2
```

### Bug Investigation
```bash
uv run cclaude run "Investigate and fix the timeout bug in API client" \
  --max-time 30
```

### Research Tasks
```bash
uv run cclaude run "Research and document caching strategies for our use case" \
  --max-iterations 5
```

## Output

The runner provides:
- Real-time iteration progress
- Learning extraction counts
- Final summary with:
  - Total iterations
  - Total learnings captured
  - Total cost
  - Duration

## Integration with Other Features

### Handoffs
- Create handoff before starting: `uv run cclaude handoff show`
- Runner context includes recent handoffs
- Create handoff after incomplete runs

### Learnings
- Automatically extracted and saved to ledger
- Use learning tags in output for capture
- Search results available: `uv run cclaude search`

### Outcomes
- Record outcomes for applied learnings afterward
- Helps improve confidence scores

## Best Practices

### 1. Start with Clear Goals
Provide specific, actionable prompts:
```bash
# Good
"Add input validation to all API endpoints with proper error messages"

# Too vague
"Improve the code"
```

### 2. Set Appropriate Limits
- **Simple tasks**: 5-10 iterations
- **Feature development**: 10-20 iterations
- **Large refactors**: 15-25 iterations
- **Always set cost limits** for budget control

### 3. Review Learnings After
```bash
uv run cclaude list -p . --min-confidence 0.5
```

### 4. Create Handoff if Incomplete
If stopped before completion:
```bash
uv run cclaude handoff create --pending "Remaining work"
```

### 5. Monitor Progress
The runner shows real-time progress. If iterations seem unproductive, stop and adjust the prompt.

## Troubleshooting

### Runner Stops Too Early
- Check stop conditions - maybe stale threshold is too low
- Review learnings - are they being extracted properly?
- Increase `--stale-threshold`

### Claude Waits Instead of Continuing
- This is the main pain point we've addressed
- Runner includes strong autonomy instructions
- PostToolUse hook nudges continuation
- If still happening, check hook configuration

### No Learnings Extracted
- Use explicit tags: `[DISCOVERY]`, `[DECISION]`, `[ERROR]`, `[PATTERN]`
- Check output format matches expected patterns
- Rebuild search index: `uv run cclaude reindex`
