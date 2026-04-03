# Claude Cortex

Persistent memory that makes Claude Code smarter across sessions.

Install. Restart. That's it.

## What Happens When You Install Cortex

- Claude remembers what worked and what didn't — across projects
- Learnings have confidence scores that improve with outcomes
- Work-in-progress is captured automatically, never lost to compaction
- Cross-project knowledge surfaces when relevant
- Code structure is tracked for dependency analysis

## What You Don't Need To Do

- Learn CLI commands — everything runs via hooks and MCP tools
- Manually tag learnings — hooks handle extraction
- Record outcomes — auto-promoted at high confidence
- Create handoffs — auto-captured before compaction
- Promote learnings — auto-promoted at >0.8 confidence + 2 outcomes

## Install

```bash
cd ~/projects/claude-cortex
./install.sh
```

Or as a Claude Code plugin:

```bash
claude plugin install claude-cortex@claude-cortex --scope user
```

Restart Claude Code. You're done.

## How It Works

### Automatic Hooks (zero effort)

| Hook | What It Does | Token Cost |
|------|-------------|------------|
| **SessionStart** | Injects pending work + top 3 learnings | ~180 tokens |
| **PostToolUse** | Silently tracks learning references | 0 tokens |
| **PreCompact** | Saves handoff + summary + extracts tagged learnings | ~25 tokens |
| **SessionEnd** | Extracts learnings, auto-promotes to global ledger | 0 tokens |
| **SubagentStop** | Tracks agent deployment effectiveness | 0 tokens |

### MCP Tools (on-demand, ~10ms)

Claude calls these naturally when it needs context:

| Tool | Purpose |
|------|---------|
| `search_learnings` | Full-text search with category/confidence filters |
| `get_learning` | Get full learning details by ID |
| `list_learnings` | List learnings sorted by confidence |
| `record_outcome` | Record success/partial/failure outcome |
| `ledger_stats` | Get ledger statistics |
| `get_handoff` | Get latest work-in-progress handoff |
| `get_suggestions` | Cross-project learning suggestions |
| `tag_learning` | Programmatic learning capture |
| `get_session_summary` | Recent session summaries |
| `entity_search` | Search code entities (functions, classes, etc.) |
| `entity_show` | Entity details with dependencies/dependents |
| `entity_stats` | Code entity graph statistics |

### Agents (7 specialized)

| Agent | Model | Trigger |
|-------|-------|---------|
| `code-implementer` | opus | "implement this", "write code for" |
| `test-writer` | sonnet | "write tests for", "add test coverage" |
| `research-agent` | opus | "research how to", "investigate options" |
| `refactorer` | sonnet | "refactor this", "clean up the code" |
| `bug-investigator` | opus | "debug this", "why is this failing" |
| `continuous-runner` | opus | "keep working", "run continuously", "plan this" |
| `knowledge-retriever` | haiku | "what did we learn", "previous patterns" |

### Skills (3)

| Skill | Purpose |
|-------|---------|
| `ledger-knowledge` | Query, search, and retrieve from ledger |
| `learning-capture` | Capture insights to ledger |
| `handoff-management` | Save/load work-in-progress state |

## Learning Tags

Tag insights as you work — they're captured automatically:

```
[DISCOVERY] PyRosetta DDG requires consistent repacking for WT and mutant
[DECISION] Using fcntl.flock() for file locking — atomic and handles crashes
[ERROR] Don't modify block files after creation — breaks hash verification
[PATTERN] For backwards compat, use Optional with defaults in Pydantic models
```

### Privacy Suffixes

| Suffix | Stored | Promoted to Global | Content |
|--------|--------|-------------------|---------|
| `[DISCOVERY]` (default) | Yes | Yes | Original |
| `[DISCOVERY:project]` | Yes | No | Original |
| `[DISCOVERY:private]` | No | N/A | Not stored |
| `[DISCOVERY:redacted]` | Yes | Yes | [REDACTED] |

## Confidence & Reinforcement

- **Outcomes**: Success +10%, Partial +2%, Failure -15%
- **Decay**: 180-day half-life, minimum 50% floor
- **Auto-promote**: Project → global at confidence >0.8 with 2+ outcomes
- **Deduplication**: Content-hashed, rediscovery boosts confidence

## Entity Graph (Code Structure)

Tree-sitter extraction tracks functions, classes, methods, imports and their relationships.

| Language | File Extensions | Entities Extracted |
|----------|----------------|-------------------|
| Python | `.py` | Classes, functions, methods, imports |
| TypeScript | `.ts`, `.tsx` | Classes, functions, interfaces, imports |
| JavaScript | `.js`, `.jsx` | Classes, functions, imports |
| Rust | `.rs` | Structs, enums, traits, functions, methods, imports |

```bash
# Index your codebase
uv run cclaude entities index .

# Search for entities
uv run cclaude entities search "UserAuth"
```

Or use MCP tools: `entity_search`, `entity_show`, `entity_stats`.

## CLI Commands (Admin/Debug)

The CLI is optional — for advanced users who want direct control:

```bash
# List/search learnings
uv run cclaude list --min-confidence 0.7
uv run cclaude search "authentication"

# Record outcomes
uv run cclaude outcome <id> -r success -c "Applied successfully"

# Verify ledger integrity
uv run cclaude verify --merkle --signatures

# Key management (Ed25519 signing)
uv run cclaude keys generate --name "You"
uv run cclaude keys trust key.pem --name "Alice"

# Sync between machines
uv run cclaude sync export backup.tar.gz
uv run cclaude sync import backup.tar.gz

# Git/PR ingestion
uv run cclaude ingest git --since 30d
uv run cclaude ingest pr

# Entity graph
uv run cclaude entities index .
uv run cclaude entities search "MyClass"

# Search index repair
uv run cclaude reindex
```

## Architecture

```
~/.claude/
├── ledger/                    # Global ledger (cross-project knowledge)
│   ├── blocks/*.json          # Immutable learning blocks
│   ├── objects/               # Content-addressed storage
│   ├── index.json             # Chain index
│   ├── reinforcements.json    # Confidence scores + outcomes
│   ├── merkle.json            # Merkle tree for sync
│   └── identity.json          # Ed25519 signing identity
├── cache/
│   ├── search.db              # SQLite FTS5 index
│   └── semantic.db            # Semantic search vectors
└── hooks/                     # Installed hook scripts

project/.claude/
├── ledger/                    # Project-specific ledger
├── handoffs/                  # Work-in-progress captures
├── summaries/                 # Session summaries
└── cache/entities.db          # Entity graph (SQLite)

~/projects/claude-cortex/
├── .claude-plugin/plugin.json # Plugin manifest (v0.2.0)
├── agents/                    # 7 agent definitions
├── skills/                    # 3 skill definitions
├── hooks/                     # Hook scripts + shared utilities
├── src/claude_cortex/         # Python package
│   ├── ledger/                # Blockchain implementation
│   ├── entities/              # Code entity graph (tree-sitter)
│   ├── ingest/                # Git/PR ingestion
│   ├── search/                # FTS5 + semantic search
│   ├── handoff/               # WIP state capture
│   ├── summaries/             # Session summaries
│   ├── suggestions/           # Cross-project recommendations
│   ├── analysis/              # LLM-powered session analysis
│   ├── mcp_server.py          # 12 MCP tools
│   └── cli.py                 # Admin CLI
├── tui/                       # Terminal dashboard (Bun/Ink)
└── tests/                     # 527 tests
```

## Development

```bash
uv sync
uv run pytest                  # Run tests (527 passing)
uv run cclaude --help          # CLI
cd tui && bun install && bun run tui  # TUI dashboard
```

## License

MIT — see [LICENSE](LICENSE) for details.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.
