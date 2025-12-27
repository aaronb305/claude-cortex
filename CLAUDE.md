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
├── agents/                    # Custom agents (11 total)
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

## Commands

- Install deps: `uv sync`
- Run tests: `uv run pytest`
- CLI: `uv run cclaude`
