---
name: search-learnings
description: Full-text search across all learnings with BM25 relevance ranking. Triggers on "search learnings", "find in ledger", "search for pattern".
allowed-tools: Bash, Read
---

# Search Learnings Skill

The continuous-claude system includes SQLite FTS5 full-text search for fast, relevance-ranked queries across all learnings.

## Basic Search

```bash
# Search for any term
uv run cclaude search "authentication"

# Search for phrases
uv run cclaude search "JWT tokens"

# Search with multiple terms (AND)
uv run cclaude search "redis caching"
```

## Filtered Search

```bash
# Search only patterns
uv run cclaude search "validation" --category pattern

# Search only errors/gotchas
uv run cclaude search "timeout" --category error

# Search only discoveries
uv run cclaude search "API" --category discovery

# Search only decisions
uv run cclaude search "database" --category decision
```

## Search Options

```bash
uv run cclaude search <query> [options]

Options:
  --category TEXT   Filter by category (discovery, decision, error, pattern)
  --project PATH    Search project ledger at PATH
  --limit INTEGER   Maximum results (default: 20)
```

## Search Syntax

### Basic Terms
- `authentication` - Find learnings containing "authentication"
- `JWT tokens` - Find learnings containing both "JWT" AND "tokens"

### Stemming
The search uses Porter stemming, so:
- `authenticate` matches `authentication`, `authenticated`, `authenticating`
- `cache` matches `caching`, `cached`, `caches`

### Unicode Support
Full unicode61 tokenizer support for international text.

## Understanding Results

Search results include:
- **Learning ID** - For referencing or recording outcomes
- **Category** - discovery, decision, error, or pattern
- **Confidence** - Current confidence score (0.0-1.0)
- **Snippet** - Matching text with highlights
- **Rank** - BM25 relevance score

## Rebuilding the Index

If learnings aren't appearing in search, rebuild the index:

```bash
# Rebuild global ledger index
uv run cclaude reindex

# Rebuild project ledger index
uv run cclaude reindex --project /path/to/project
```

## Use Cases

### Before Starting Work
Search for relevant prior knowledge:
```bash
uv run cclaude search "user registration"
uv run cclaude search "form validation" --category pattern
```

### Debugging Issues
Find known errors and gotchas:
```bash
uv run cclaude search "timeout error" --category error
uv run cclaude search "race condition"
```

### Architecture Decisions
Review past decisions on a topic:
```bash
uv run cclaude search "database" --category decision
uv run cclaude search "caching strategy"
```

### Finding Patterns
Discover reusable solutions:
```bash
uv run cclaude search "repository" --category pattern
uv run cclaude search "error handling"
```

## Integration with Ledger

Search is automatically updated when new blocks are added to the ledger. The index is stored at:

```
~/.claude/cache/search.db       # Global ledger index
project/.claude/cache/search.db # Project ledger index
```

## Tips

1. **Start broad, then filter** - Search general terms first, add category filters to narrow
2. **Use stemming** - Don't worry about exact word forms
3. **Check both ledgers** - Global may have cross-project knowledge
4. **Record outcomes** - When a search result helps, record the outcome to boost its confidence
