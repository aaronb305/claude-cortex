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

## Dependencies

### Core Features (Included)
All core functionality works out of the box:

| Feature | Description | Dependencies |
|---------|-------------|--------------|
| Ledger storage | Blockchain-style learning storage | pydantic, click (included) |
| Full-text search | FTS5 keyword search | sqlite3 (Python stdlib) |
| Handoffs | Work-in-progress state capture | (included) |
| Summaries | Transcript summary storage | (included) |
| Confidence decay | Time-based confidence adjustment | (included) |
| Cross-project transfer | Learning suggestions & import | (included) |
| File locking | Race condition prevention | fcntl (Python stdlib) |

### Optional Features

| Feature | Description | Install Command |
|---------|-------------|-----------------|
| **Semantic search** | Vector similarity search | `uv sync --extra semantic` |

**Semantic search** enables finding related learnings even with different wording (e.g., "authentication" matches "login security"). Adds ~500MB of dependencies (ML model).

```bash
# Option 1: Install via extras (recommended)
uv sync --extra semantic

# Option 2: Install all optional features
uv sync --extra all

# Option 3: Install packages directly
uv add sentence-transformers sqlite-vec

# Verify installation
uv run python -c "from continuous_claude.search.semantic import is_available; print(is_available())"
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
- **SessionStart**: Injects high-confidence learnings + latest handoff + recent summaries
- **PostToolUse**: Nudges continuation when tasks remain, tracks learning references
- **PreCompact**: Saves handoff + summary + extracts learnings before compaction
- **SessionEnd**: Extracts new learnings from transcript, suggests outcome recording

### Agents

All agents use **opus** as the default model.

**Execution Agents** (deploy for focused work):
| Agent | Trigger |
|-------|---------|
| `code-implementer` | "implement this", "write code for" |
| `test-writer` | "write tests for", "add test coverage" |
| `research-agent` | "research how to", "investigate options" |
| `refactorer` | "refactor this", "clean up the code" |
| `bug-investigator` | "debug this", "why is this failing" |
| `doc-writer` | "document this", "update README" |

**Coordination Agents** (deploy for workflows):
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

# Summary commands
uv run cclaude summary show [session_id]
uv run cclaude summary list

# Cross-project suggestions
uv run cclaude suggest                    # Show relevant learnings from global ledger
uv run cclaude suggest -n 5               # Limit to 5 suggestions
uv run cclaude suggest --apply <id>       # Import a suggestion to project ledger
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

## Learning Tags

Use these tags in your responses to mark learnings:

```
[DISCOVERY] New information about the codebase
[DECISION] Architectural choices made
[ERROR] Mistakes or gotchas to avoid
[PATTERN] Reusable solutions identified
```

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
│   ├── index.json             # Chain index
│   └── reinforcements.json    # Confidence scores + outcomes
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
├── handoffs/                  # Work-in-progress captures
│   └── <session>/handoff-<timestamp>.md
├── summaries/                 # Conversation summaries
│   └── <session>/summary-<timestamp>.json
└── session_learnings.json     # Learnings referenced in current session

~/projects/continuous-claude-custom/
├── .claude-plugin/            # Plugin manifest
├── agents/                    # Custom agents (11 total)
├── skills/                    # Skills (5)
├── hooks/                     # Hook scripts
│   ├── shared.py              # Shared utilities (file locking, extraction)
│   ├── session_start.py       # Inject ledger context + handoff
│   ├── session_end.py         # Extract learnings + outcome suggestions
│   ├── pre_compact.py         # Pre-compaction handoff + summary + extraction
│   └── post_tool_use.py       # Continuation nudges + learning tracking
├── src/continuous_claude/     # Python package
│   ├── ledger/                # Blockchain implementation (chain.py, models.py)
│   ├── runner/                # Continuous execution
│   ├── handoff/               # WIP state capture
│   ├── summaries/             # Transcript summary storage
│   ├── search/                # SQLite FTS5 + semantic search
│   ├── suggestions/           # Cross-project recommendation engine
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

## Commands

- Install deps: `uv sync`
- Run tests: `uv run pytest`
- CLI: `uv run cclaude`
