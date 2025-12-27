---
name: learning-capture
description: Capture and persist learnings to the blockchain ledger. Use when discovering important insights, making significant decisions, encountering errors worth remembering, or identifying reusable patterns. Essential for building persistent memory across sessions.
allowed-tools: Bash, Write, Read
---

# Learning Capture Skill

This skill enables explicit capture of learnings to the continuous-claude blockchain ledger, ensuring valuable insights persist across sessions.

## When to Capture

### Discoveries (🔍)
- Finding out how a system works
- Discovering undocumented API behavior
- Learning about codebase architecture
- Performance characteristics found

**Example triggers:**
- "I found that..."
- "It turns out..."
- "The system actually..."

### Decisions (⚖️)
- Choosing a technology or approach
- Making architectural decisions
- Selecting patterns or conventions
- Resolving tradeoffs

**Example triggers:**
- "We decided to..."
- "Going with X because..."
- "Chose this approach since..."

### Errors (⚠️)
- Mistakes made and how to avoid them
- Gotchas and edge cases
- Failed approaches
- Debugging insights

**Example triggers:**
- "Don't do X because..."
- "Watch out for..."
- "This doesn't work when..."

### Patterns (🔄)
- Reusable code patterns
- Naming conventions
- File organization strategies
- Testing approaches

**Example triggers:**
- "The pattern for X is..."
- "Always use Y for..."
- "Convention is to..."

## Tagging Format

Use these tags in your responses to mark learnings:

```
[DISCOVERY] The API rate limits at 100 requests per minute
[DECISION] Using Redis for caching due to pub/sub requirements
[ERROR] Don't use async in middleware - breaks error handling
[PATTERN] All services implement the IService interface
```

## Manual Capture

Use the learn command to explicitly capture:

```bash
cd ~/projects/continuous-claude-custom && uv run python -c "
import json
import hashlib
from datetime import datetime
from pathlib import Path
from uuid import uuid4

# Configure
CATEGORY = 'discovery'  # discovery, decision, error, pattern
CONTENT = 'Your learning content here'
LEDGER_PATH = Path.home() / '.claude' / 'ledger'  # or Path('.claude/ledger')

# Ensure structure
LEDGER_PATH.mkdir(parents=True, exist_ok=True)
(LEDGER_PATH / 'blocks').mkdir(exist_ok=True)

index_file = LEDGER_PATH / 'index.json'
if not index_file.exists():
    index_file.write_text('{\"head\": null, \"blocks\": []}')

reinforcements_file = LEDGER_PATH / 'reinforcements.json'
if not reinforcements_file.exists():
    reinforcements_file.write_text('{\"learnings\": {}}')

# Read state
index = json.loads(index_file.read_text())
reinforcements = json.loads(reinforcements_file.read_text())

# Create learning
learning = {
    'id': str(uuid4()),
    'category': CATEGORY,
    'content': CONTENT,
    'confidence': 0.6,
    'source': None,
    'outcomes': []
}

# Create block
block_id = str(uuid4())[:8]
block = {
    'id': block_id,
    'timestamp': datetime.utcnow().isoformat(),
    'session_id': 'manual',
    'parent_block': index.get('head'),
    'learnings': [learning]
}
block['hash'] = hashlib.sha256(json.dumps(block, sort_keys=True, default=str).encode()).hexdigest()

# Save
(LEDGER_PATH / 'blocks' / f'{block_id}.json').write_text(json.dumps(block, indent=2))
index['head'] = block_id
index['blocks'].append({'id': block_id, 'timestamp': block['timestamp'], 'hash': block['hash'], 'parent': block.get('parent_block')})
index_file.write_text(json.dumps(index, indent=2))
reinforcements['learnings'][learning['id']] = {'category': CATEGORY, 'confidence': 0.6, 'outcome_count': 0, 'last_updated': datetime.utcnow().isoformat()}
reinforcements_file.write_text(json.dumps(reinforcements, indent=2))

print(f'✓ Captured: {learning[\"id\"][:8]} [{CATEGORY}]')
"
```

## Automatic Capture

Learnings tagged with `[DISCOVERY]`, `[DECISION]`, `[ERROR]`, or `[PATTERN]` are automatically captured by the SessionEnd hook when the session ends.

## Quality Guidelines

Good learnings are:
- **Specific**: "The auth API uses RS256 JWT" not "auth stuff"
- **Actionable**: Can be applied in future work
- **Verified**: Based on actual experience
- **Concise**: Under 200 characters ideal
- **Sourced**: Include file paths when relevant

## Recording Outcomes

After applying a learning, record the outcome to adjust confidence:

```bash
cd ~/projects/continuous-claude-custom && uv run cclaude outcome <id> -r success -c "Applied in auth refactor"
```

Outcomes affect confidence:
- success: +0.10
- partial: +0.02
- failure: -0.15
