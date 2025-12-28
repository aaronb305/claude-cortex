---
name: outcome-prompt
description: Suggests outcome recording for recently referenced learnings. Use this skill to check if any learnings from the current or recent sessions need outcome feedback, and to prompt the user for recording outcomes. Essential for maintaining accurate confidence scores in the ledger. **Complexity indicator**: Quick check and suggestion operation. For in-depth outcome analysis or batch recording, use the `outcome-tracker` agent or CLI commands instead.
allowed-tools: Bash, Read
---

# Outcome Prompt Skill

This skill helps maintain the quality of the continuous-claude ledger by suggesting outcome recording for learnings that have been applied.

## Purpose

The ledger's confidence scoring system depends on outcome feedback. When learnings are applied:
- **Successful** applications increase confidence (+0.10)
- **Partial** applications slightly increase confidence (+0.02)
- **Failed** applications decrease confidence (-0.15)

Without outcome feedback, confidence scores stagnate and don't reflect real-world accuracy.

## When to Use

### Automatic Detection
The SessionEnd hook automatically detects referenced learnings and suggests outcomes. Use this skill when:

- You want to check for pending outcomes mid-session
- The user mentions applying a learning from the ledger
- After completing a task that used documented patterns
- When the user says "that worked" or "that didn't work"

### Trigger Phrases
- "check for pending outcomes"
- "any learnings need feedback"
- "did that pattern work"
- "record outcome for"

## Checking for Pending Outcomes

### List Recently Referenced Learnings
```bash
cd ~/projects/continuous-claude-custom && uv run cclaude outcomes pending
```

This shows learnings that:
1. Were referenced in recent sessions
2. Have fewer than 3 recorded outcomes

### List All Learnings Needing Feedback
```bash
cd ~/projects/continuous-claude-custom && uv run cclaude outcomes pending --all
```

Shows all learnings with low outcome counts, not just recently referenced ones.

## Recording Outcomes

### Single Outcome
```bash
# Success
uv run cclaude outcome <learning_id> -r success -c "Description of how it worked"

# Partial success
uv run cclaude outcome <learning_id> -r partial -c "What worked and what needed adjustment"

# Failure
uv run cclaude outcome <learning_id> -r failure -c "Why it didn't work"
```

### Batch Recording
```bash
uv run cclaude outcomes batch
```

Interactive mode that walks through learnings needing outcomes.

## Prompting Format

When suggesting outcome recording to the user, use this format:

```
## Outcome Recording Suggestion

The following learnings were referenced and may benefit from outcome feedback:

| ID | Category | Confidence | Content Preview |
|----|----------|------------|-----------------|
| abc12345 | pattern | 60% | Use Redis for caching with... |
| def67890 | decision | 75% | Always validate JWT tokens... |

**Quick Actions:**

For the first learning (abc12345):
- If it worked: `uv run cclaude outcome abc12345 -r success -c "your description"`
- If it partially worked: `uv run cclaude outcome abc12345 -r partial -c "your description"`
- If it didn't work: `uv run cclaude outcome abc12345 -r failure -c "your description"`

Or use batch mode: `uv run cclaude outcomes batch`
```

## Session Tracking

Learning references are tracked automatically:

1. **During Session**: The `post_tool_use` hook detects learning IDs in tool outputs
2. **Tracking File**: References stored in `.claude/session_learnings.json`
3. **At Session End**: The `session_end` hook suggests outcomes for tracked learnings
4. **Cleanup**: Tracking file is cleared after processing

### Manual Session File Inspection
```bash
cat .claude/session_learnings.json
```

Example content:
```json
{
  "referenced_learnings": ["abc12345", "def67890"],
  "session_id": "session-uuid",
  "last_updated": "2024-01-15T10:30:00"
}
```

## Best Practices

### 1. Record Promptly
- Record outcomes while context is fresh
- Don't wait until the end of the session if you know the result

### 2. Be Honest
- Accurate outcomes improve the ledger's reliability
- Partial success is valuable information
- Failures help prevent future mistakes

### 3. Provide Context
Good context examples:
- "Applied in auth middleware, worked as documented"
- "Pattern worked but needed timeout adjustment for our use case"
- "Failed because our API uses different authentication flow"

Poor context examples:
- "worked"
- "failed"
- "used it"

### 4. Regular Maintenance
Periodically check for learnings with low outcome counts:
```bash
uv run cclaude outcomes pending --all --limit 30
```

## Integration

### With outcome-tracker Agent
For complex outcome analysis or when multiple outcomes need recording, deploy the `outcome-tracker` agent instead.

### With learning-capture Skill
After capturing a new learning, monitor for its first application and record the outcome.

### With session-continuity Agent
When resuming sessions, check if previously applied learnings had successful outcomes.
