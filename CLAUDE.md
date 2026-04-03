# Claude Cortex

Blockchain-style ledger memory with performance-based reinforcement for Claude Code.

## Installation

```bash
# Install from local directory
cd ~/projects/claude-cortex
./install.sh

# Or install plugin from local marketplace
claude plugin install claude-cortex@claude-cortex --scope user
```

This will:
1. Install the Python package with `uv`
2. Set up hooks in `~/.claude/hooks/`
3. Configure Claude Code settings
4. Initialize the global ledger at `~/.claude/ledger/`

## Dependencies

All features are included by default with `uv sync`:

| Feature | Description | Dependencies |
|---------|-------------|--------------|
| Ledger storage | Blockchain-style learning storage | pydantic, click |
| Full-text search | FTS5 keyword search | sqlite3 (Python stdlib) |
| Semantic search | Vector similarity search | fastembed, sqlite-vec |
| Cryptographic signing | Ed25519 block signatures | cryptography |
| Content-addressed storage | Deduplication via content hash | (included) |
| Distributed sync | Merkle-based ledger sync | (included) |
| Handoffs | Work-in-progress state capture | (included) |
| Summaries | Transcript summary storage | (included) |
| Confidence decay | Time-based confidence adjustment | (included) |
| Cross-project transfer | Learning suggestions & import | (included) |
| File locking | Race condition prevention | fcntl (Python stdlib) |
| Git/PR ingestion | Extract learnings from commits & PRs | gh CLI (for PRs) |
| Entity graph | Code structure tracking | tree-sitter-language-pack |
| MCP tools | Low-latency Claude Code integration | mcp |

### External Requirements

| Requirement | Purpose | Install |
|-------------|---------|---------|
| Python 3.10+ | Runtime | System package manager |
| uv | Package management | `pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| gh CLI | GitHub PR ingestion | `brew install gh` or system package manager |

### Verify Installation

```bash
# Check all dependencies installed
uv sync

# Verify semantic search
uv run python -c "from claude_cortex.search.semantic import is_available; print(is_available())"

# Verify entity extraction
uv run python -c "from claude_cortex.entities.extractors import get_extractor_for_file; print(get_extractor_for_file('test.py'))"
```

## Usage

### Automatic Operation (Recommended)

Once the plugin is installed, **everything works automatically**. Just use Claude as usual:

1. **Session starts** → Relevant learnings and context are injected automatically
2. **You work normally** → Tag insights with `[DISCOVERY]`, `[DECISION]`, `[ERROR]`, `[PATTERN]` when appropriate
3. **Session ends** → Learnings are extracted and stored in the ledger
4. **Context is preserved** → Handoffs and summaries are saved before compaction

**No CLI commands required for normal operation.**

### Automatic Hooks

The plugin uses hooks to provide seamless integration:
- **SessionStart**: Injects slim context (~180 tokens): pending work + top 3 learnings + MCP pointer
- **PostToolUse**: Silent learning reference tracking (zero token injection)
- **PreCompact**: Saves handoff + summary + extracts learnings before compaction
- **SessionEnd**: Extracts learnings, auto-promotes high-confidence learnings, suggests outcomes
- **SubagentStop**: Tracks agent deployments and effectiveness when subagents complete

### MCP Tools

| Tool | Purpose |
|------|---------|
| `search_learnings` | Full-text search with category/confidence filters |
| `get_learning` | Get full learning details by ID |
| `record_outcome` | Record success/partial/failure outcome |
| `list_learnings` | List learnings sorted by confidence |
| `ledger_stats` | Get ledger statistics |
| `get_handoff` | Get latest handoff for session continuity |
| `get_suggestions` | Cross-project learning suggestions |
| `tag_learning` | Programmatic learning capture |
| `get_session_summary` | Recent session summaries |
| `entity_search` | Search code entities by name |
| `entity_show` | Entity details with dependencies/dependents |
| `entity_stats` | Entity graph statistics |

### Agents

**Execution Agents** (deploy for focused work):
| Agent | Model | Trigger |
|-------|-------|---------|
| `code-implementer` | opus | "implement this", "write code for" (includes docs) |
| `test-writer` | sonnet | "write tests for", "add test coverage" |
| `research-agent` | opus | "research how to", "investigate options" |
| `refactorer` | sonnet | "refactor this", "clean up the code" |
| `bug-investigator` | opus | "debug this", "why is this failing" |

**Coordination Agents** (deploy for workflows):
| Agent | Model | Trigger |
|-------|-------|---------|
| `continuous-runner` | opus | "keep working", "run continuously", "plan this" |
| `knowledge-retriever` | haiku | "what did we learn", "previous patterns" |

### Skills

| Skill | Purpose |
|-------|---------|
| `ledger-knowledge` | Query, search, and retrieve from ledger |
| `learning-capture` | Capture insights to ledger |
| `handoff-management` | Save/load work-in-progress state |

### CLI Commands (Optional Power Tools)

These commands are **optional** for advanced users who want direct control:

```bash
# Run continuous mode (autonomous iteration)
uv run cclaude run "Add tests" --max-iterations 10

# List learnings
uv run cclaude list --min-confidence 0.7

# Show learning details
uv run cclaude show <id>
uv run cclaude show <id> --show-decay     # Include effective confidence with decay

# List with confidence decay info
uv run cclaude list --min-confidence 0.7 --show-decay

# Record outcome (updates confidence)
uv run cclaude outcome <id> -r success -c "Applied successfully"

# View pending outcomes (learnings used but not rated)
uv run cclaude outcomes pending

# Batch process pending feedback
uv run cclaude outcomes batch

# Promote to global ledger
uv run cclaude promote -p . --threshold 0.8

# Verify chain integrity
uv run cclaude verify
uv run cclaude verify --merkle              # Also verify Merkle tree
uv run cclaude verify --signatures          # Verify block signatures

# Search learnings (full-text)
uv run cclaude search "authentication"
uv run cclaude search "pattern" --category pattern

# Rebuild search index
uv run cclaude reindex
uv run cclaude reindex --repair           # Retry only previously failed indexing

# Handoff commands
uv run cclaude handoff create --completed "Task 1" --pending "Task 2"
uv run cclaude handoff show
uv run cclaude handoff list

# Summary commands
uv run cclaude summary show [session_id]
uv run cclaude summary list

# Cross-project suggestions
uv run cclaude suggest                    # Show relevant learnings from global ledger
uv run cclaude suggest -n 5               # Limit to 5 suggestions
uv run cclaude suggest --apply <id>       # Import a suggestion to project ledger

# Content cache migration (performance optimization)
uv run cclaude migrate                    # Populate content cache in reinforcements.json

# Git/PR ingestion (extract learnings from commit history)
uv run cclaude ingest git                 # Ingest from git commits
uv run cclaude ingest git --since 30d     # Last 30 days
uv run cclaude ingest git --tags-only     # Only explicit [DISCOVERY] etc. tags
uv run cclaude ingest git --dry-run       # Preview without saving
uv run cclaude ingest pr                  # Ingest from GitHub PRs
uv run cclaude ingest pr --since 2w       # PRs from last 2 weeks
uv run cclaude ingest status              # Show ingestion state
uv run cclaude ingest reset               # Reset ingestion state

# Entity graph commands (code structure tracking)
uv run cclaude entities index .           # Index entities in directory
uv run cclaude entities index . --force   # Force re-index all files
uv run cclaude entities show <name>       # Show entity details by qualified name
uv run cclaude entities search <query>    # Search entities by name
uv run cclaude entities stats             # Show entity graph statistics
uv run cclaude entities clear             # Clear the entity graph
```

## Git/PR Ingestion

Extract learnings from your git commit history and GitHub pull requests.

### Git Commit Ingestion

Automatically extracts learnings from conventional commits and explicit learning tags:

```bash
# Ingest commits from the last 30 days
uv run cclaude ingest git --since 30d

# Only extract from explicit [DISCOVERY] [DECISION] [ERROR] [PATTERN] tags
uv run cclaude ingest git --tags-only

# Filter by author
uv run cclaude ingest git --author "john@example.com"

# Preview what would be extracted (dry run)
uv run cclaude ingest git --dry-run --limit 50
```

**Learning Sources from Commits:**

| Source | Category | Confidence |
|--------|----------|------------|
| `[DISCOVERY]` tag | DISCOVERY | 0.65+ |
| `[DECISION]` tag | DECISION | 0.65+ |
| `[ERROR]` tag | ERROR | 0.65+ |
| `[PATTERN]` tag | PATTERN | 0.65+ |
| `feat:` commits | DISCOVERY | 0.55+ |
| `fix:` commits | ERROR | 0.55+ |
| `refactor:` commits | PATTERN | 0.55+ |
| `docs:` commits | DECISION | 0.55+ |

**Confidence Boosts:**
- +0.05 for detailed messages (>100 chars)
- +0.10 for very detailed messages (>200 chars)
- +0.05 for co-authored commits (implies review)

### GitHub PR Ingestion

Extract learnings from PR descriptions, reviews, and comments:

```bash
# Ingest merged PRs
uv run cclaude ingest pr

# Ingest PRs from specific timeframe
uv run cclaude ingest pr --since 2w

# Specific PR by number
uv run cclaude ingest pr 123

# Include all states (not just merged)
uv run cclaude ingest pr --state all

# Control what's extracted
uv run cclaude ingest pr --no-reviews     # Skip review comments
uv run cclaude ingest pr --no-comments    # Skip discussion comments

# Specify repository (defaults to current git remote)
uv run cclaude ingest pr --repo owner/repo
```

**Requires:** GitHub CLI (`gh`) authenticated via `gh auth login`

**What's Extracted:**
- PR descriptions with explicit learning tags
- "Breaking Changes" sections → ERROR category
- "Why/Motivation" sections → DECISION category
- CHANGES_REQUESTED reviews → ERROR category
- Inline code comments with learning tags

### Incremental Ingestion

The system tracks ingestion progress per-project:

```bash
# Check current state
uv run cclaude ingest status

# Resume from where you left off (automatic)
uv run cclaude ingest git

# Reset and start fresh
uv run cclaude ingest reset --source git
```

State is stored in `.claude/ingestion_state.json`.

## Entity Graph (Code Structure Tracking)

Track code structure relationships using tree-sitter for intelligent codebase understanding.

### What It Does

The entity graph extracts and stores code entities (classes, functions, methods) and their relationships (imports, inheritance, calls) from your codebase. This enables:

- **Dependency tracking**: See what code depends on what
- **Impact analysis**: Understand what might break when changing code
- **Codebase navigation**: Find related code across files

### Supported Languages

| Language | File Extensions | Entities Extracted |
|----------|----------------|-------------------|
| Python | `.py` | Classes, functions, methods, imports |
| TypeScript | `.ts`, `.tsx` | Classes, functions, interfaces, imports |
| JavaScript | `.js`, `.jsx` | Classes, functions, imports |
| Rust | `.rs` | Structs, enums, traits, functions, methods, imports |

### CLI Commands

```bash
# Index all supported files in a directory
uv run cclaude entities index .
uv run cclaude entities index ./src --force   # Force re-index

# Search for entities by name
uv run cclaude entities search "UserAuth"

# Show entity details and relationships
uv run cclaude entities show "src/auth.py:UserAuth"

# View statistics
uv run cclaude entities stats

# Clear the entity graph
uv run cclaude entities clear
```

### Storage Location

Entity graphs are stored per-project in `.claude/cache/entities.db` (SQLite).

### Dependencies

Entity extraction requires the `tree-sitter-language-pack` package:

```bash
# Already included in default dependencies
uv sync

# Or install explicitly
uv add tree-sitter-language-pack
```

### How It Works

1. **Indexing**: Files are parsed with tree-sitter to extract entities
2. **Staleness detection**: Files are only re-indexed when content changes (MD5 hash)
3. **Relationship tracking**: Imports, inheritance, and function calls are linked
4. **Full-text search**: Entity names are indexed with SQLite FTS5

## Continuous Execution Mode

Run Claude in autonomous continuous mode for multi-iteration tasks with automatic learning extraction.

### Quick Start

```bash
# Basic continuous run (10 iterations max)
uv run cclaude run "Implement user authentication"

# With custom limits
uv run cclaude run "Refactor auth module" \
  --max-iterations 20 \
  --max-cost 5.0 \
  --max-time 60 \
  --stale-threshold 3
```

### Command Options

```bash
uv run cclaude run <prompt> [options]

Options:
  -p, --project PATH       Project directory (default: current)
  --max-iterations INT     Maximum iterations (default: 10)
  --max-cost FLOAT         Maximum cost in USD
  --max-time INT           Maximum time in minutes
  --stale-threshold INT    Stop after N iterations without new learnings
```

### Stop Conditions

The runner stops when ANY condition is met:

| Condition | Flag | Description |
|-----------|------|-------------|
| Iteration limit | `--max-iterations` | Maximum number of iterations |
| Cost limit | `--max-cost` | Maximum API cost in USD |
| Time limit | `--max-time` | Maximum execution time in minutes |
| Stale detection | `--stale-threshold` | N iterations without new learnings |

### Recommended Limits

- **Simple tasks**: 5-10 iterations
- **Feature development**: 10-20 iterations
- **Large refactors**: 15-25 iterations
- **Always set cost limits** for budget control

### Troubleshooting

**Runner stops too early:**
- Increase `--stale-threshold`
- Check if learnings are being extracted (use explicit tags)

**No learnings extracted:**
- Use explicit tags: `[DISCOVERY]`, `[DECISION]`, `[ERROR]`, `[PATTERN]`
- Rebuild search index: `uv run cclaude reindex`

## Sync Commands

```bash
uv run cclaude sync status                # Show sync status and Merkle root
uv run cclaude sync pull /path/to/remote  # Pull blocks from remote
uv run cclaude sync push /path/to/remote  # Push blocks to remote
uv run cclaude sync export backup.tar.gz  # Export to archive
uv run cclaude sync import backup.tar.gz  # Import from archive
```

## Key Management

```bash
uv run cclaude keys generate --name "You" # Generate signing keypair
uv run cclaude keys show                  # Show your public key
uv run cclaude keys export -o key.pem     # Export public key
uv run cclaude keys trust key.pem --name "Bob"  # Add trusted key
uv run cclaude keys list                  # List trusted keys
uv run cclaude keys revoke <key_id>       # Remove trusted key
```

## Cross-Project Learning Transfer

The system supports transferring knowledge between projects:

### Intelligent Suggestions

The `suggest` command analyzes your current project to find relevant learnings from the global ledger:

- **Project type detection** - Python, Node.js, Rust, Go, etc.
- **Tech stack matching** - FastAPI, React, pytest, etc.
- **Keyword relevance** - Matches content against your project's README and CLAUDE.md

### Learning Genealogy

Learnings track their origin:
- `derived_from` - Links imported learnings to their source
- `promoted_to` - Tracks where a learning was promoted
- `project_context` - Records project type, tech stack, and keywords

### Session Context

The SessionStart hook automatically shows 2-3 top suggestions from the global ledger when starting a new session in a project directory.

## Learning Tags - IMMEDIATE TAGGING

**CRITICAL**: Tag learnings IMMEDIATELY when they occur, not later. This ensures insights are captured before context compaction or session end.

### When to Tag

Tag immediately after:
- **Fixing a bug** → What was wrong and why
- **Making an architecture decision** → What you chose and why
- **Discovering how something works** → The insight gained
- **Finding a gotcha or pitfall** → What to avoid next time
- **Identifying a reusable pattern** → The generalizable solution

### Tag Format

```
[DISCOVERY] <specific insight with enough context to understand standalone>
[DECISION] <what was decided and the rationale>
[ERROR] <what went wrong and how to avoid it>
[PATTERN] <reusable solution that applies beyond this specific case>
```

### Privacy Suffixes

Control how learnings are stored and shared with privacy suffixes:

```
[DISCOVERY:private] API key format is ABC-XXX  # Never stored
[PATTERN:project] Our internal auth pattern    # Stays in project ledger only
[ERROR:redacted] Credentials in config file    # Content replaced with [REDACTED]
[DECISION] Standard public learning            # Default: can be promoted to global
```

| Privacy Level | Stored | Promoted to Global | Content |
|---------------|--------|-------------------|---------|
| `public` (default) | Yes | Yes | Original |
| `project` | Yes | No | Original |
| `private` | No | N/A | Not stored |
| `redacted` | Yes | Yes | Replaced with [REDACTED] |

### Examples

```
[DISCOVERY] PyRosetta DDG requires consistent repacking - use PackRotamersMover
with identical TaskFactory for both WT and mutant, not FastRelax on mutant only.

[DECISION] Using fcntl.flock() for file locking instead of a lock file approach
because it's atomic and handles process crashes gracefully.

[ERROR] Don't modify block files after creation - it breaks hash verification.
Store mutable data (outcomes, confidence) in reinforcements.json instead.

[PATTERN] For backwards compatibility when adding fields to Pydantic models,
always use Optional with defaults and create a hash_dict() method that returns
only the original fields for hash computation.
```

### Why Immediate Tagging Matters

- Context compaction can happen anytime → Learnings in compacted context are lost
- Session can end unexpectedly → No chance to extract later
- Immediate tagging captures full context → Better quality learnings
- System has safety nets but they're **backups**, not primary capture

## Confidence & Reinforcement

### Confidence Decay

Learnings decay in confidence over time if not actively used:
- **Half-life**: 180 days - confidence drops to 50% of stored value
- **Minimum floor**: 50% - learnings never decay below half their stored confidence
- **Reset on use**: Applying a learning (`touch_learning()`) resets the decay clock

Use `--show-decay` to see both stored and effective confidence:
```bash
uv run cclaude list --show-decay
uv run cclaude show abc123 --show-decay
```

### Outcome Recording

When learnings are referenced in a session, the system tracks them for outcome feedback:
- **Session end**: Suggests recording outcomes for referenced learnings
- **Confidence adjustment**: Success +10%, Partial +2%, Failure -15%
- **Preserves immutability**: Outcomes stored in reinforcements.json, not blocks

```bash
# Record outcome
uv run cclaude outcome <id> -r success -c "Worked perfectly"
uv run cclaude outcome <id> -r partial -c "Needed minor adjustment"
uv run cclaude outcome <id> -r failure -c "Did not apply to this context"

# View learnings awaiting feedback
uv run cclaude outcomes pending
```

### Deduplication

Learnings are deduplicated using normalized content hashing:
- **Normalization**: lowercase, strip whitespace, collapse internal whitespace
- **Hash**: First 16 chars of SHA-256
- **Rediscovery boost**: When the same insight is discovered again, confidence increases

## Architecture

```
~/.claude/
├── ledger/                    # Global ledger
│   ├── blocks/*.json          # Immutable blocks
│   ├── objects/               # Content-addressed storage (sharded by hash prefix)
│   │   └── ab/ab12cd34.json   # Content files stored by hash
│   ├── index.json             # Chain index
│   ├── reinforcements.json    # Confidence scores + outcomes + content cache
│   ├── merkle.json            # Merkle tree for efficient sync/verification
│   ├── identity.json          # This ledger's public key + identity
│   ├── .private_key           # Private signing key (mode 600)
│   └── trusted_keys.json      # Trusted public keys from other users
├── cache/
│   ├── search.db              # SQLite FTS5 search index
│   └── semantic.db            # Semantic search vectors (optional)
├── hooks/
│   ├── session_start.py       # Inject ledger context + handoff
│   ├── post_tool_use.py       # Continuation nudges
│   ├── pre_compact.py         # Pre-compaction handoff + extraction
│   └── session_end.py         # Extract learnings
└── settings.json              # Hooks configuration

project/.claude/
├── ledger/                    # Project-specific ledger
│   ├── merkle.json            # Merkle tree for this ledger
│   ├── identity.json          # Project-specific identity (optional)
│   └── trusted_keys.json      # Trusted keys for this project
├── handoffs/                  # Work-in-progress captures
│   └── <session>/handoff-<timestamp>.md
├── summaries/                 # Conversation summaries
│   └── <session>/summary-<timestamp>.json
├── insights/                  # LLM-powered session analysis results
│   └── <session>/insights-<timestamp>.json
└── session_learnings.json     # Learnings referenced in current session

~/projects/claude-cortex/
├── .claude-plugin/            # Plugin manifest
├── agents/                    # Custom agents (7 total)
├── skills/                    # Skills (3)
├── hooks/                     # Hook scripts
│   ├── shared.py              # Shared utilities (file locking, extraction)
│   ├── session_start.py       # Inject ledger context + handoff
│   ├── session_end.py         # Extract learnings + outcome suggestions
│   ├── pre_compact.py         # Pre-compaction handoff + summary + extraction
│   ├── post_tool_use.py       # Continuation nudges + learning tracking
│   ├── subagent_stop.py       # Agent deployment tracking + effectiveness
│   └── stop.py                # Learning tagging nudges
├── src/claude_cortex/         # Python package
│   ├── ledger/                # Blockchain implementation
│   │   ├── chain.py           # Ledger management + search integration
│   │   ├── models.py          # Learning, Block, Outcome models
│   │   ├── merkle.py          # Merkle tree for efficient sync
│   │   ├── objects.py         # Content-addressed storage
│   │   └── crypto.py          # Ed25519 signing and verification
│   ├── ingest/                # Git/PR ingestion
│   │   ├── git_extractor.py   # Git commit parsing + learning extraction
│   │   ├── github_client.py   # GitHub API via gh CLI
│   │   ├── pr_extractor.py    # PR/review learning extraction
│   │   ├── patterns.py        # Extraction regex patterns
│   │   └── state.py           # Incremental ingestion state
│   ├── runner/                # Continuous execution
│   ├── handoff/               # WIP state capture
│   ├── summaries/             # Transcript summary storage
│   ├── search/                # SQLite FTS5 + semantic search
│   ├── suggestions/           # Cross-project recommendation engine
│   ├── analysis/              # LLM-powered session analysis
│   ├── entities/              # Code entity graph (tree-sitter)
│   │   ├── graph.py           # EntityGraph database management
│   │   ├── models.py          # Entity, Relationship models
│   │   ├── schema.py          # SQLite schema with FTS5
│   │   └── extractors/        # Language-specific extractors
│   │       ├── python.py      # Python AST extraction
│   │       └── typescript.py  # TypeScript/TSX extraction
│   ├── sync.py                # Ledger sync protocol (export/import)
│   └── cli.py                 # CLI interface
├── tests/                     # Test suite
└── install.sh                 # Installation script
```

## Orchestration Patterns

### The Main Claude Instance as Orchestrator

When working on tasks, the main Claude instance should:
1. **Assess complexity** - How many steps? How much context needed?
2. **Choose tool type** - Agent for complex, Skill for quick
3. **Track progress** - Use TodoWrite continuously
4. **Deploy resources** - Launch agents/skills as needed

### Task Complexity Assessment

| Complexity | Indicators | Action |
|------------|------------|--------|
| LOW | Single file, quick lookup, direct query | Use SKILL directly |
| MEDIUM | 2-3 steps, known pattern, focused scope | Consider SKILL or AGENT |
| HIGH | Multi-step, research needed, context-dependent | Deploy AGENT |

### Agent vs Skill Decision Tree

```
Is this a multi-step workflow requiring analysis?
├─ YES → Deploy AGENT(s) in parallel when possible
│        ├─ code-implementer, test-writer (can run together)
│        ├─ research-agent (independent)
│        └─ continuous-runner (for coordination)
└─ NO → Is it a quick lookup or direct operation?
    ├─ YES → Use SKILL (e.g., ledger-knowledge, search-learnings)
    └─ NO → Assess complexity, default to AGENT for unknowns
```

### Parallel Execution Pattern

Deploy multiple agents simultaneously for independent tasks:
```
Example: "Implement feature X with tests"
├─ Deploy code-implementer → writes the feature
├─ Deploy test-writer → writes tests (parallel)
├─ Deploy research-agent → checks patterns (parallel)
└─ Collect results and synthesize next steps
```

### Recommended Workflows

#### Feature Development (Parallel Agents)
1. `research-agent` → check existing patterns (parallel)
2. `code-implementer` → implement feature (parallel)
3. `test-writer` → write tests (parallel)
4. Collect results, integrate
5. `doc-writer` → update documentation
6. `outcome-tracker` → record what worked

#### Quick Research
1. `search-learnings` skill → find specific knowledge
2. `ledger-knowledge` skill → get learning details
3. Direct response to user (no agent needed)

#### Session Resume
1. SessionStart hook auto-loads handoff and learnings
2. `session-continuity` agent → if full restoration needed
3. OR `handoff-management` skill → just load/display handoff

#### Long-Running Tasks
1. `continuous-runner` agent → for autonomous multi-iteration work
2. OR direct work with continuous TodoWrite updates
3. `learning-extractor` agent → extract insights at end

## Data Integrity

The system ensures data integrity through several mechanisms:

### File Locking
All ledger operations use `fcntl.flock()` to prevent race conditions when multiple processes access the ledger simultaneously.

### Block Immutability
Blocks are write-once. Outcomes and confidence updates are stored in `reinforcements.json` separately from the immutable block chain.

### Chain Verification
```bash
uv run cclaude verify              # Verify chain integrity
```

### Merkle Tree Verification

The ledger maintains a Merkle tree (`merkle.json`) for efficient integrity verification and sync:

- **Automatic updates**: Tree is rebuilt after each block is appended
- **O(log n) diff**: Efficiently find which blocks differ between ledgers
- **Tamper detection**: Root hash changes if any block is modified

The Merkle tree is built from sorted block IDs for deterministic trees across machines.

## Distributed Sync

The sync module enables synchronization between ledgers on different machines.

### Sync Commands

```bash
# Check sync status (also updates merkle.json)
uv run cclaude sync status
uv run cclaude sync status -p .          # Project ledger

# Pull blocks from a remote ledger
uv run cclaude sync pull /path/to/remote/ledger
uv run cclaude sync pull ~/backup/ledger --dry-run

# Push blocks to a remote ledger
uv run cclaude sync push /path/to/remote/ledger
uv run cclaude sync push /mnt/backup/ledger -p .

# Export to archive (for transfer between machines)
uv run cclaude sync export ~/ledger-backup.tar.gz
uv run cclaude sync export ./project-ledger.tar.gz -p .

# Import from archive (merges with existing)
uv run cclaude sync import ~/ledger-backup.tar.gz
uv run cclaude sync import ./project-ledger.tar.gz -p .
```

### How Sync Works

1. **Merkle Tree Comparison**: Compares Merkle roots to detect differences in O(1)
2. **Block Set Diff**: Identifies missing blocks in each direction
3. **Hash Verification**: Each imported block's hash is verified before acceptance
4. **Index Update**: Chain index is updated to include new blocks in correct order

Sync status values:
- `IN_SYNC` - Ledgers are identical (same Merkle root)
- `LOCAL_AHEAD` - Local has blocks remote doesn't have
- `REMOTE_AHEAD` - Remote has blocks local doesn't have
- `DIVERGED` - Both have unique blocks (bidirectional sync needed)

### Archive Contents

Export archives (`*.tar.gz`) include:
- `blocks/*.json` - Immutable block files
- `index.json` - Chain index with head pointer
- `reinforcements.json` - Mutable confidence/outcome data

## Content-Addressed Storage

Learnings are stored in a content-addressed object store for deduplication.

### How It Works

Objects are stored by their content hash in a sharded directory structure:
```
objects/
  ab/
    ab12cd34ef56.json  # 16-char hash as filename
  cd/
    cd78ef90ab12.json
```

### Benefits

- **Automatic deduplication**: Same content = same hash = stored once
- **Efficient lookup**: O(1) content retrieval by hash
- **Cross-ledger sharing**: Global and project ledgers can share content
- **Integrity verification**: Hash serves as checksum

### reinforcements.json Integration

The `object_store_hash` field in `reinforcements.json` links learnings to their content:
```json
{
  "learnings": {
    "abc123...": {
      "confidence": 0.8,
      "object_store_hash": "ab12cd34ef567890",
      "content": "cached content for fast access"
    }
  }
}
```

## Cryptographic Signatures

Blocks can be signed with Ed25519 keys for authenticity verification.

### Key Generation

```bash
# Generate a signing keypair
uv run cclaude keys generate --name "Your Name"
uv run cclaude keys generate -p . --name "Project Key"

# View your public key
uv run cclaude keys show
uv run cclaude keys export -o my_key.pem
```

### Trust Management

```bash
# Add a trusted public key
uv run cclaude keys trust colleague_key.pem --name "Colleague" --level full
uv run cclaude keys trust team_key.pem --name "Team Member" --level marginal

# List trusted keys
uv run cclaude keys list

# Revoke a trusted key
uv run cclaude keys revoke <key_id>
```

Trust levels:
- `full` - Fully trusted, signatures from this key are accepted
- `marginal` - Partially trusted, may require additional verification
- `none` - Not trusted, signatures are rejected

### Signature Verification

```bash
# Verify all block signatures
uv run cclaude verify --signatures

# Combined verification (chain + merkle + signatures)
uv run cclaude verify --merkle --signatures
```

### How Signing Works

1. **Block Creation**: When a block is appended, it's signed with the ledger's private key
2. **Signature Storage**: Signatures are stored in `blocks/<id>.sig` files
3. **Verification**: Signatures are verified against trusted keys during sync and verify

Signature file format:
```json
{
  "key_id": "ABC123",
  "signature": "base64-encoded-signature"
}
```

## Content Caching

The `migrate` command populates a content cache in `reinforcements.json`:

```bash
uv run cclaude migrate             # Migrate global ledger
uv run cclaude migrate -p .        # Migrate project ledger
```

**Why this matters**: SessionStart hook performance improves from O(n*m) to O(1) for content lookups. Without the cache, the hook must scan all blocks to find learning content. With the cache, content is available directly in `reinforcements.json`.

## Search Index Recovery

If the search index becomes corrupted or out of sync:

```bash
# Full reindex - rebuilds entire index from blocks
uv run cclaude reindex

# Repair mode - retry only previously failed indexing operations
uv run cclaude reindex --repair
```

The `--repair` flag is faster when only a few learnings failed to index. It reads `failed_indexing.json` and retries those specific learnings.

## Session Analysis

LLM-powered analysis provides Braintrust-like insights from session transcripts:

```bash
# Analyze a session transcript
uv run cclaude analyze session transcript.md

# Save insights to project directory
uv run cclaude analyze session transcript.md -p . --save-learnings

# Use regex-only extraction (faster, no LLM cost)
uv run cclaude analyze session transcript.md --no-llm

# View aggregated metrics across sessions
uv run cclaude analyze metrics -p .
```

Analysis extracts:
- **What Worked**: Successful approaches and decisions
- **What Failed**: Errors, dead ends, incorrect assumptions
- **Patterns**: Reusable solutions and workflows
- **Key Decisions**: Important choices made during the session
- **Metrics**: Duration, turns, tool usage, success rates

## MCP Tools

Claude Cortex exposes ledger operations as MCP (Model Context Protocol) tools for low-latency access from Claude Code.

### Available Tools

| Tool | Description |
|------|-------------|
| `search_learnings` | Full-text search with category filtering |
| `get_learning` | Get full details of a learning by ID |
| `record_outcome` | Record success/partial/failure outcome |
| `list_learnings` | List learnings by confidence |
| `ledger_stats` | Get ledger statistics |

### Configuration

MCP is auto-configured via `.mcp.json` in the plugin directory:

```json
{
  "mcpServers": {
    "claude-cortex": {
      "command": "uv",
      "args": ["run", "python", "-m", "claude_cortex.mcp_server"],
      "cwd": "${CLAUDE_PLUGIN_ROOT}",
      "env": {"PYTHONPATH": "${CLAUDE_PLUGIN_ROOT}/src"}
    }
  }
}
```

### Usage

MCP tools are available via `/mcp` in Claude Code:
- `search_learnings("authentication")` - Search for learnings
- `get_learning("abc123", show_decay=True)` - Get learning with decay info
- `record_outcome("abc123", "success", "Worked perfectly")` - Record outcome

## TUI Dashboard

A terminal user interface for browsing and managing learnings.

### Quick Start

```bash
cd tui
bun install
bun run tui
```

### Keyboard Shortcuts

**Navigation (Vim-style):**
| Key | Action |
|-----|--------|
| `j` / `Down Arrow` | Move down in list |
| `k` / `Up Arrow` | Move up in list |
| `g` | Jump to first item |
| `G` | Jump to last item |
| `Enter` | View selected item details |
| `Esc` | Go back / close |

**Views:**
| Key | Action |
|-----|--------|
| `l` | Show list view (from detail) |
| `/` | Open search |
| `Tab` | Toggle search input focus |

**Actions:**
| Key | Action |
|-----|--------|
| `r` | Refresh data |
| `q` | Quit application |

## Confidence-Weighted Extraction

Learnings are assigned confidence based on their extraction source:

| Source | Default Confidence | Description |
|--------|-------------------|-------------|
| `USER_TAGGED` | 0.70 | User explicitly tagged with [DISCOVERY], etc. |
| `STOP_HOOK` | 0.50 | Auto-detected by stop hook patterns |
| `LLM_ANALYSIS` | 0.40 | AI extracted from transcript |
| `CONSENSUS` | 0.85 | Multiple sources agree |

### Two-Pass Extraction

1. **Fast pass** (default): Extract tagged content only
2. **Deep pass** (optional): Run LLM analysis for additional insights

Enable deep pass in settings when fast pass yields few results.

## Settings Configuration

Configure behavior via `.claude/cortex-settings.json`:

```json
{
  "session_start": {
    "global_learning_limit": 3,
    "project_learning_limit": 3,
    "global_min_confidence": 0.8,
    "project_min_confidence": 0.7,
    "show_orchestration_guidance": false,
    "handoff_max_completed_tasks": 3,
    "handoff_max_pending_tasks": 5,
    "summary_limit": 2,
    "summary_max_length": 300,
    "suggestion_limit": 2
  },
  "extraction": {
    "user_tagged_confidence": 0.70,
    "stop_hook_confidence": 0.50,
    "llm_analysis_confidence": 0.40,
    "consensus_confidence": 0.85,
    "enable_deep_pass": false,
    "deep_pass_threshold": 3
  },
  "privacy": {
    "default_level": "public",
    "allow_private_tag": true,
    "allow_project_tag": true
  }
}
```

Settings are loaded from:
1. Global: `~/.claude/cortex-settings.json`
2. Project: `.claude/cortex-settings.json` (overrides global)

## Commands

- Install deps: `uv sync`
- Run tests: `uv run pytest`
- CLI: `uv run cclaude`
- TUI: `cd tui && bun run tui`
