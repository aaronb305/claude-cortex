# Continuous Claude Custom

Blockchain-style ledger memory with performance-based reinforcement for Claude Code.

## Installation

```bash
# Install from local directory
cd ~/projects/continuous-claude-custom
./install.sh

# Or install plugin from local marketplace
claude plugin install continuous-claude@continuous-claude-custom --scope user
```

This will:
1. Install the Python package with `uv`
2. Set up hooks in `~/.claude/hooks/`
3. Configure Claude Code settings
4. Initialize the global ledger at `~/.claude/ledger/`

## Usage

### Normal Claude (with ledger context)

Just use Claude as usual - hooks automatically:
- **SessionStart**: Injects high-confidence learnings + latest handoff
- **PostToolUse**: Nudges continuation when tasks remain
- **PreCompact**: Saves handoff + extracts learnings before compaction
- **SessionEnd**: Extracts new learnings from transcript

### Agents

All agents use **opus** as the default model.

| Agent | Trigger |
|-------|---------|
| `continuous-runner` | "keep working", "run continuously" |
| `knowledge-retriever` | "what did we learn", "previous patterns" |
| `learning-extractor` | "extract learnings", end of session |
| `session-continuity` | "resume my work", "what was I working on" |
| `outcome-tracker` | "record outcome", "this worked" |

### Skills

| Skill | Purpose |
|-------|---------|
| `ledger-knowledge` | Query and retrieve from ledger |
| `learning-capture` | Capture insights to ledger |
| `handoff-management` | Save/load work-in-progress state |
| `search-learnings` | Full-text search across learnings |
| `continuous-execution` | Run autonomous iteration mode |

### CLI Commands

```bash
# Run continuous mode
uv run cclaude run "Add tests" --max-iterations 10

# List learnings
uv run cclaude list --min-confidence 0.7

# Show learning details
uv run cclaude show <id>

# Record outcome (updates confidence)
uv run cclaude outcome <id> -r success -c "Applied successfully"

# Promote to global ledger
uv run cclaude promote -p . --threshold 0.8

# Verify chain integrity
uv run cclaude verify

# Search learnings (full-text)
uv run cclaude search "authentication"
uv run cclaude search "pattern" --category pattern

# Rebuild search index
uv run cclaude reindex

# Handoff commands
uv run cclaude handoff create --completed "Task 1" --pending "Task 2"
uv run cclaude handoff show
uv run cclaude handoff list
```

## Learning Tags

Use these tags in your responses to mark learnings:

```
[DISCOVERY] New information about the codebase
[DECISION] Architectural choices made
[ERROR] Mistakes or gotchas to avoid
[PATTERN] Reusable solutions identified
```

## Architecture

```
~/.claude/
├── ledger/                    # Global ledger
│   ├── blocks/*.json          # Immutable blocks
│   ├── index.json             # Chain index
│   └── reinforcements.json    # Confidence scores
├── cache/
│   └── search.db              # SQLite FTS5 search index
├── hooks/
│   ├── session_start.py       # Inject ledger context + handoff
│   ├── post_tool_use.py       # Continuation nudges
│   ├── pre_compact.py         # Pre-compaction handoff + extraction
│   └── session_end.py         # Extract learnings
└── settings.json              # Hooks configuration

project/.claude/
├── ledger/                    # Project-specific ledger
└── handoffs/                  # Work-in-progress captures
    └── <session>/handoff-<timestamp>.md

~/projects/continuous-claude-custom/
├── .claude-plugin/            # Plugin manifest
├── agents/                    # Custom agents (5)
├── skills/                    # Skills (5)
├── hooks/                     # Hook scripts
├── src/continuous_claude/     # Python package
│   ├── ledger/                # Blockchain implementation
│   ├── runner/                # Continuous execution
│   ├── handoff/               # WIP state capture
│   ├── search/                # SQLite FTS5 search
│   └── cli.py                 # CLI interface
└── install.sh                 # Installation script
```

## Commands

- Install deps: `uv sync`
- Run tests: `uv run pytest`
- CLI: `uv run cclaude`
