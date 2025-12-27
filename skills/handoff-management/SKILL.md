---
name: handoff-management
description: Manage work-in-progress handoffs for session continuity. Use when you need to save current work state, resume from a previous session, or review what was in progress. Triggers on "save my progress", "create handoff", "show handoff", "list handoffs". **Complexity indicator**: Quick save/load operations for work-in-progress state. For full session context restoration with analysis of learnings and git state, use the `session-continuity` agent instead.
allowed-tools: Bash, Read, Write
---

# Handoff Management Skill

Handoffs capture work-in-progress state, enabling seamless session continuity. Unlike learnings (permanent knowledge), handoffs capture ephemeral state: what's done, what's pending, and what's blocking progress.

## When to Use Handoffs

### Save Progress
- Before ending a session with incomplete work
- Before context compaction (automatic via PreCompact hook)
- When switching between tasks

### Resume Work
- Starting a new session on existing work
- After context was cleared or compacted
- Picking up where you left off

## Handoff Commands

### Create a Handoff

```bash
# Basic handoff
uv run cclaude handoff create

# With specific tasks
uv run cclaude handoff create \
  --completed "Implemented auth middleware" \
  --completed "Added JWT validation" \
  --pending "Write integration tests" \
  --pending "Add password reset flow" \
  --blocker "Need API credentials for OAuth" \
  --context "Using RS256 for token signing"
```

### View Latest Handoff

```bash
uv run cclaude handoff show
```

### List All Handoffs

```bash
uv run cclaude handoff list
```

## Handoff Format

Handoffs are stored as markdown with YAML frontmatter:

```markdown
---
session_id: abc-123
timestamp: 2025-12-27T14:30:00+00:00
---

## Completed
- Implemented auth middleware
- Added JWT validation

## Pending
- Write integration tests
- Add password reset flow

## Modified Files
- src/auth/middleware.py
- src/auth/jwt.py

## Blockers
- Need API credentials for OAuth

## Context
Using RS256 for token signing. The auth service expects tokens
in the Authorization header, not cookies.
```

## Storage Location

```
project/.claude/handoffs/
└── <session_id>/
    └── handoff-<timestamp>.md
```

## Best Practices

### When Creating Handoffs

1. **Be specific about pending tasks**
   - Bad: "Finish auth"
   - Good: "Write integration tests for JWT refresh flow"

2. **Document blockers clearly**
   - What's blocking?
   - What's needed to unblock?
   - Who can help?

3. **Include relevant context**
   - Key decisions made
   - Important file paths
   - Configuration details

### When Resuming

1. **Read the handoff first** - Understand what was in progress
2. **Check modified files** - Review recent changes
3. **Address blockers** - Can they be resolved now?
4. **Update the todo list** - Convert pending items to todos

## Automatic Handoffs

The PreCompact hook automatically creates a handoff before context compaction, capturing:
- Tasks from the conversation
- Modified files (from git status)
- Any mentioned blockers

## Integration with Learnings

Handoffs are for **ephemeral state** (current work), while learnings are for **permanent knowledge**:

| Aspect | Handoffs | Learnings |
|--------|----------|-----------|
| Lifespan | Session-bound | Permanent |
| Content | Tasks, blockers, files | Insights, patterns |
| Confidence | N/A | 0.0-1.0 with outcomes |
| Promotion | N/A | Project → Global |

When completing work captured in a handoff, consider extracting permanent insights as learnings:

```
[DISCOVERY] The OAuth flow requires PKCE for mobile clients
[DECISION] Using httpOnly cookies for refresh tokens due to XSS concerns
```
