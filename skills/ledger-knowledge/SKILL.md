---
name: ledger-knowledge
description: Query the blockchain-style knowledge ledger for prior learnings, patterns, and decisions. Triggers on "list learnings", "show learning", "check the ledger", "what do we know about".
allowed-tools: Bash, Read
---

# Ledger Knowledge Skill

This skill provides access to the claude-cortex knowledge ledger, enabling retrieval of learnings from previous sessions.

## Ledger Locations

- **Global ledger**: `~/.claude/ledger/` - Knowledge across all projects
- **Project ledger**: `./.claude/ledger/` - Project-specific knowledge

## Ledger Structure

```
ledger/
├── blocks/           # Immutable learning blocks (JSON)
│   ├── abc123.json
│   └── def456.json
├── index.json        # Chain index with block references
└── reinforcements.json  # Confidence scores and outcome counts
```

## Commands

### List learnings
```bash
uv run cclaude list [options]
```

Options:
- `--min-confidence 0.7` - Filter by confidence threshold
- `--category discovery` - Filter by category
- `--limit 20` - Limit results
- `-p .` - Query project ledger instead of global

### Show learning details
```bash
uv run cclaude show <learning_id>
```

### Verify chain integrity
```bash
uv run cclaude verify
```

## Learning Categories

| Category | Description |
|----------|-------------|
| discovery | New information about codebases, APIs, patterns |
| decision | Architectural choices and rationale |
| error | Mistakes to avoid, gotchas, failed approaches |
| pattern | Reusable solutions, conventions, templates |

## Confidence Levels

- **0.9-1.0**: Highly reliable, proven through multiple successes
- **0.7-0.9**: Reliable, has positive outcome history
- **0.5-0.7**: Moderate, initial learnings or mixed outcomes
- **0.3-0.5**: Uncertain, may need verification
- **0.0-0.3**: Unreliable, consider reviewing or removing

## Usage Examples

**Find patterns for authentication:**
```bash
uv run cclaude list --category pattern | grep -i auth
```

**Get high-confidence learnings:**
```bash
uv run cclaude list --min-confidence 0.8
```

**Check project-specific knowledge:**
```bash
uv run cclaude list -p . --limit 10
```

## Integration Notes

- Learnings are automatically extracted from sessions via SessionEnd hook
- Confidence adjusts based on recorded outcomes (success/failure/partial)
- High-confidence project learnings can be promoted to global ledger
