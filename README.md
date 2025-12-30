# Continuous Claude Custom

A blockchain-style ledger memory system with performance-based reinforcement learning for Claude Code. This plugin enables persistent knowledge capture across sessions with confidence scoring, autonomous execution capabilities, and cross-project knowledge transfer.

## Features

### Core Capabilities

- **Blockchain-style Ledger**: Immutable knowledge storage with SHA-256 hash verification
- **Merkle Tree Verification**: O(log n) sync and tamper detection using binary merkle trees
- **Cryptographic Signatures**: Ed25519 block signing with trust-based key management
- **Content-Addressed Storage**: Automatic deduplication via content hashing in `objects/` directory
- **Distributed Sync**: Pull/push between ledgers with Merkle-based diff detection
- **Confidence Scoring**: Reinforcement learning that adjusts learning reliability based on outcomes
- **Dual Ledger System**: Global (`~/.claude/ledger/`) and project-specific (`.claude/ledger/`) knowledge bases
- **Ledger Sync**: Export/import archives for backup and transfer between machines
- **Autonomous Execution**: Enhanced prompts and hooks for continuous, uninterrupted work
- **Learning Extraction**: Automatic capture of discoveries, decisions, errors, and patterns
- **Handoff System**: Work-in-progress state capture for seamless session continuity
- **Full-Text Search**: SQLite FTS5 search across all learnings with relevance ranking
- **Session Analysis**: LLM-powered Braintrust-like insights from session transcripts

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
uv run cclaude list --show-decay          # Show confidence decay info

# Show learning details
uv run cclaude show <learning-id>

# Record outcome (updates confidence)
uv run cclaude outcome <learning-id> -r success -c "Applied successfully"
uv run cclaude outcomes pending           # View learnings needing feedback

# Promote high-confidence learnings to global
uv run cclaude promote -p . --threshold 0.8

# Verify ledger chain integrity
uv run cclaude verify

# Search learnings (full-text search)
uv run cclaude search "authentication JWT"
uv run cclaude search "pattern" --category pattern

# Rebuild/repair search index
uv run cclaude reindex
uv run cclaude reindex --repair           # Retry failed indexing only

# Handoffs (work-in-progress capture)
uv run cclaude handoff create --completed "Finished auth" --pending "Add tests"
uv run cclaude handoff show
uv run cclaude handoff list

# Summaries
uv run cclaude summary show
uv run cclaude summary list

# Cross-project suggestions
uv run cclaude suggest                    # Show relevant learnings from global
uv run cclaude suggest --apply <id>       # Import suggestion to project

# Content cache migration (performance)
uv run cclaude migrate

# Session analysis (Braintrust-like insights)
uv run cclaude analyze session transcript.md --save-learnings
uv run cclaude analyze metrics -p .

# Sync between ledgers
uv run cclaude sync status                # Check sync state
uv run cclaude sync pull /path/to/remote  # Pull missing blocks
uv run cclaude sync push /path/to/remote  # Push local blocks
uv run cclaude sync export backup.tar.gz  # Export to archive
uv run cclaude sync import backup.tar.gz  # Import from archive

# Key management (Ed25519 signing)
uv run cclaude keys generate --name "You" # Create keypair
uv run cclaude keys trust key.pem --name "Alice"  # Add trusted key
uv run cclaude keys list                  # List trusted keys
uv run cclaude keys revoke <key_id>       # Revoke a key

# Verification with signatures
uv run cclaude verify --merkle --signatures
```

### Agents

All agents use **opus** as the default model for maximum capability.

**Execution Agents** (deploy for focused, parallelizable work):

| Agent | Trigger | Purpose |
|-------|---------|---------|
| `code-implementer` | "implement this", "write code for" | Write/modify code for specific tasks |
| `test-writer` | "write tests for", "add test coverage" | Create tests (can run parallel with implementation) |
| `research-agent` | "research how to", "investigate options" | Investigate APIs, libraries, patterns |
| `refactorer` | "refactor this", "clean up the code" | Restructure code while preserving behavior |
| `bug-investigator` | "debug this", "why is this failing" | Debug and trace issues to find root causes |
| `doc-writer` | "document this", "update README" | Write/update documentation |

**Coordination Agents** (deploy for multi-step workflows):

| Agent | Trigger | Purpose |
|-------|---------|---------|
| `continuous-runner` | "keep working", "run continuously" | Coordinate autonomous multi-iteration sessions |
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
| `outcome-prompt` | Suggest outcome recording for applied learnings |

## Architecture

```
~/.claude/
├── ledger/                    # Global ledger (cross-project knowledge)
│   ├── blocks/*.json          # Immutable learning blocks
│   ├── objects/               # Content-addressed storage (sharded by hash)
│   │   └── ab/ab12cd34.json   # Content stored by 16-char hash
│   ├── index.json             # Chain index with head pointer
│   ├── reinforcements.json    # Confidence scores, outcomes, content cache
│   ├── merkle.json            # Merkle tree for efficient sync/verification
│   ├── identity.json          # This ledger's public key + identity
│   ├── .private_key           # Private signing key (mode 600)
│   └── trusted_keys.json      # Trusted public keys from other users
├── cache/
│   ├── search.db              # SQLite FTS5 search index
│   └── semantic.db            # Semantic search vectors (optional)
├── hooks/
│   ├── session_start.py       # Inject ledger context
│   ├── post_tool_use.py       # Continuation nudges
│   ├── pre_compact.py         # Pre-compaction extraction
│   └── session_end.py         # Extract learnings
└── settings.json              # Hook configuration

project/.claude/
├── ledger/                    # Project-specific ledger
│   ├── merkle.json            # Merkle tree for this ledger
│   ├── identity.json          # Project-specific signing identity
│   └── trusted_keys.json      # Trusted keys for this project
├── handoffs/                  # Work-in-progress state captures
│   └── <session>/handoff-<timestamp>.md
├── summaries/                 # Session summaries
│   └── <session>/summary-<timestamp>.json
└── insights/                  # LLM-powered analysis results
    └── <session>/insights-<timestamp>.json

~/projects/continuous-claude-custom/
├── .claude-plugin/plugin.json # Plugin manifest
├── agents/                    # Custom agents (11 total, opus model)
├── skills/                    # User-invocable skills (6)
├── hooks/                     # Hook implementations
├── src/continuous_claude/     # Python package
│   ├── ledger/                # Blockchain ledger implementation
│   │   ├── chain.py           # Ledger management + search integration
│   │   ├── models.py          # Learning, Block, Outcome models
│   │   ├── merkle.py          # Merkle tree for efficient sync
│   │   ├── objects.py         # Content-addressed object store
│   │   └── crypto.py          # Ed25519 signing and verification
│   ├── runner/                # Continuous execution
│   ├── handoff/               # Work-in-progress state capture
│   ├── summaries/             # Session summary storage
│   ├── search/                # Full-text + semantic search
│   ├── suggestions/           # Cross-project recommendations
│   ├── analysis/              # LLM-powered session analysis
│   ├── sync.py                # Ledger sync protocol (export/import)
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
| Data integrity | SHA-256 blockchain + Merkle tree | None |
| Cryptographic signing | Ed25519 with trust levels | None |
| Content deduplication | Content-addressed storage | None |
| Distributed sync | Merkle-based pull/push | None |
| Confidence scoring | Yes (reinforcement) | No |
| Global knowledge | Yes (promotion) | Project-only |
| Outcome tracking | Yes | No |
| Autonomous execution | Enhanced prompts + hooks | Basic |
| Handoffs (WIP state) | Yes | Some |
| Full-text search | SQLite FTS5 | Limited |
| Sync/export | Archive-based transfer | None |
| Session analysis | LLM-powered insights | None |

## License

MIT

## Contributing

Contributions welcome! Please ensure:
- Tests pass (`uv run pytest`)
- Code follows existing patterns
- Learnings are documented with appropriate tags
