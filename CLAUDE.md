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
├─ YES → Deploy AGENT (e.g., knowledge-retriever, continuous-runner)
└─ NO → Is it a quick lookup or direct operation?
    ├─ YES → Use SKILL (e.g., ledger-knowledge, search-learnings)
    └─ NO → Assess complexity, default to AGENT for unknowns
```

### Recommended Workflows

#### Feature Development
1. `search-learnings` skill → quick check for prior work
2. `knowledge-retriever` agent → deep pattern analysis (if complex)
3. Work on implementation with continuous todo updates
4. `learning-capture` skill → tag insights as you go
5. `outcome-tracker` agent → record what worked/failed

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
