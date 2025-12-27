# Continuous Claude Custom

A blockchain-style ledger memory system with performance-based reinforcement learning for Claude Code. This plugin enables persistent knowledge capture across sessions with confidence scoring, autonomous execution capabilities, and cross-project knowledge transfer.

## Features

### Core Capabilities

- **Blockchain-style Ledger**: Immutable knowledge storage with SHA-256 hash verification
- **Confidence Scoring**: Reinforcement learning that adjusts learning reliability based on outcomes
- **Dual Ledger System**: Global (`~/.claude/ledger/`) and project-specific (`.claude/ledger/`) knowledge bases
- **Autonomous Execution**: Enhanced prompts and hooks for continuous, uninterrupted work
- **Learning Extraction**: Automatic capture of discoveries, decisions, errors, and patterns
- **Handoff System**: Work-in-progress state capture for seamless session continuity
- **Full-Text Search**: SQLite FTS5 search across all learnings with relevance ranking

### Knowledge Categories

| Tag | Purpose | Example |
|-----|---------|---------|
| `[DISCOVERY]` | New information found | API rate limits at 100/min |
| `[DECISION]` | Choices made and rationale | Using JWT for stateless auth |
| `[ERROR]` | Mistakes to avoid | Don't use sync calls in async handler |
| `[PATTERN]` | Reusable solutions | Repository pattern for data access |

## Installation

### Quick Install

```bash
cd ~/projects/continuous-claude-custom
./install.sh
```

This will:
1. Install the Python package with `uv`
2. Set up hooks in `~/.claude/hooks/`
3. Configure Claude Code settings
4. Initialize the global ledger at `~/.claude/ledger/`

### Plugin Installation

```bash
# Load plugin for testing (temporary)
claude --plugin-dir ~/projects/continuous-claude-custom

# Or install permanently from local marketplace
claude plugin install continuous-claude@continuous-claude-custom --scope user
```

### Manual Setup

```bash
# Install dependencies
uv sync

# Run the CLI
uv run cclaude --help
```

## Usage

### Automatic Knowledge Capture

Just use Claude as usual - hooks automatically:
- **SessionStart**: Inject high-confidence learnings from ledger
- **PostToolUse**: Nudge continuation when tasks remain
- **PreCompact**: Extract learnings before context compaction
- **SessionEnd**: Extract new learnings from transcript

### CLI Commands

```bash
# Run continuous execution mode
uv run cclaude run "Add authentication" -p . --max-iterations 10

# List learnings (filter by confidence)
uv run cclaude list --min-confidence 0.7

# Show learning details
uv run cclaude show <learning-id>

# Record outcome (updates confidence)
uv run cclaude outcome <learning-id> -r success -c "Applied successfully"

# Promote high-confidence learnings to global
uv run cclaude promote -p . --threshold 0.8

# Verify ledger chain integrity
uv run cclaude verify

# Search learnings (full-text search)
uv run cclaude search "authentication JWT"
uv run cclaude search "pattern" --category pattern

# Rebuild search index
uv run cclaude reindex

# Create a handoff (work-in-progress capture)
uv run cclaude handoff create --completed "Finished auth" --pending "Add tests"

# Show latest handoff
uv run cclaude handoff show

# List all handoffs
uv run cclaude handoff list
```

### Agents

All agents use **opus** as the default model for maximum capability.

| Agent | Trigger | Purpose |
|-------|---------|---------|
| `continuous-runner` | "keep working", "run continuously" | Orchestrate autonomous multi-iteration sessions |
| `knowledge-retriever` | "what did we learn", "previous patterns" | Search and surface relevant learnings |
| `learning-extractor` | "extract learnings", end of session | Analyze and categorize insights |
| `session-continuity` | "resume my work", "what was I working on" | Manage session transitions and handoffs |
| `outcome-tracker` | "record outcome", "this worked/didn't work" | Track outcomes to improve confidence scores |

### Skills

| Skill | Purpose |
|-------|---------|
| `ledger-knowledge` | Query and retrieve from ledger |
| `learning-capture` | Manually capture insights to ledger |
| `handoff-management` | Save/load work-in-progress state |
| `search-learnings` | Full-text search across learnings |
| `continuous-execution` | Run autonomous iteration mode |

## Architecture

```
~/.claude/
├── ledger/                    # Global ledger (cross-project knowledge)
│   ├── blocks/*.json          # Immutable learning blocks
│   ├── index.json             # Chain index with head pointer
│   └── reinforcements.json    # Confidence scores and outcomes
├── hooks/
│   ├── session_start.py       # Inject ledger context
│   ├── post_tool_use.py       # Continuation nudges
│   ├── pre_compact.py         # Pre-compaction extraction
│   └── session_end.py         # Extract learnings
└── settings.json              # Hook configuration

project/.claude/
├── ledger/                    # Project-specific ledger
└── handoffs/                  # Work-in-progress state captures
    └── <session>/handoff-<timestamp>.md

~/.claude/
├── cache/
│   └── search.db              # SQLite FTS5 search index

~/projects/continuous-claude-custom/
├── .claude-plugin/plugin.json # Plugin manifest
├── agents/                    # Custom agents (opus model)
│   ├── continuous-runner.md   # Autonomous iteration manager
│   ├── knowledge-retriever.md # Ledger search specialist
│   ├── learning-extractor.md  # Insight extraction specialist
│   ├── session-continuity.md  # Session transition manager
│   └── outcome-tracker.md     # Confidence score updater
├── hooks/                     # Hook implementations
├── skills/                    # User-invocable skills
├── src/continuous_claude/     # Python package
│   ├── ledger/                # Blockchain ledger implementation
│   │   ├── chain.py           # Ledger management + search integration
│   │   └── models.py          # Learning, Block, Outcome models
│   ├── runner/                # Continuous execution
│   │   ├── loop.py            # Main execution loop + autonomy prompts
│   │   ├── context.py         # Context builder
│   │   └── stop_conditions.py # Termination logic
│   ├── handoff/               # Work-in-progress state capture
│   │   ├── models.py          # Handoff dataclass
│   │   └── manager.py         # Handoff creation/loading
│   ├── search/                # Full-text search
│   │   └── index.py           # SQLite FTS5 implementation
│   └── cli.py                 # Command-line interface
└── install.sh                 # Installation script
```

## How It Works

### Blockchain Ledger

Each learning is stored in an immutable block with:
- **UUID**: Unique identifier for referencing
- **Category**: DISCOVERY, DECISION, ERROR, or PATTERN
- **Content**: The actual insight (max 500 chars)
- **Confidence**: 0.0-1.0 score, starts at 0.5
- **Hash**: SHA-256 of block contents for integrity
- **Parent**: Reference to previous block (forming a chain)

### Confidence Scoring

Confidence adjusts based on recorded outcomes:
- **SUCCESS**: +0.10 increase
- **PARTIAL**: +0.02 increase
- **FAILURE**: -0.15 decrease

High-confidence learnings (>0.8) can be promoted from project to global ledger.

### Autonomous Execution

The system encourages continuous, uninterrupted work through:
1. **Runner prompts**: Explicit instructions to continue without confirmation
2. **PostToolUse hook**: Nudges when tasks remain after tool use
3. **Agent instructions**: "Never stop unless truly blocked"
4. **TodoWrite integration**: Track progress and keep working

### Handoff System

Handoffs capture work-in-progress state for session continuity:
- **Automatic**: Created before context compaction (PreCompact hook)
- **Manual**: `cclaude handoff create` for explicit checkpoints
- **Content**: Completed tasks, pending tasks, blockers, modified files, context notes
- **Storage**: `.claude/handoffs/<session>/handoff-<timestamp>.md`
- **Injection**: Latest handoff is shown at session start

### Full-Text Search

SQLite FTS5 provides fast, relevance-ranked search:
- **Porter stemmer**: Matches word variations (e.g., "authenticate" matches "authentication")
- **BM25 ranking**: Results ordered by relevance
- **Snippets**: Highlighted matching text in results
- **Auto-indexing**: Learnings indexed when blocks are added
- **Category filtering**: `--category pattern` to narrow results

## Configuration

### Stop Conditions

The runner supports configurable stop conditions:
- `IterationLimit`: Maximum number of iterations
- `CostLimit`: Maximum API cost in USD
- `TimeLimit`: Maximum execution duration
- `NoNewLearnings`: Stop after N iterations without new learnings
- `ConfidenceThreshold`: Stop when target learning reaches confidence

### Hooks

Hooks are registered in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [{"command": "python ~/.claude/hooks/session_start.py"}],
    "PostToolUse": [{"command": "python ~/.claude/hooks/post_tool_use.py"}],
    "PreCompact": [{"command": "python ~/.claude/hooks/pre_compact.py"}],
    "SessionEnd": [{"command": "python ~/.claude/hooks/session_end.py"}]
  }
}
```

## Development

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest

# Run CLI locally
uv run cclaude --help
```

## Comparison with Similar Systems

| Feature | Continuous Claude Custom | Other Systems |
|---------|-------------------------|---------------|
| Data integrity | SHA-256 blockchain | None |
| Confidence scoring | Yes (reinforcement) | No |
| Global knowledge | Yes (promotion) | Project-only |
| Outcome tracking | Yes | No |
| Autonomous execution | Enhanced prompts + hooks | Basic |
| Handoffs (WIP state) | Yes | Some |
| Full-text search | SQLite FTS5 | Limited |

## License

MIT

## Contributing

Contributions welcome! Please ensure:
- Tests pass (`uv run pytest`)
- Code follows existing patterns
- Learnings are documented with appropriate tags
