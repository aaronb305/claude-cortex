# Claude Cortex Roadmap

## Overview

This document outlines planned improvements to Claude Cortex, informed by analysis of claude-mem and industry best practices for context engineering.

**Goals:**
1. Reduce token consumption by 60-70%
2. Add MCP tools for faster search (10x improvement)
3. Implement privacy controls
4. Add Bun-based TUI dashboard
5. Improve learning capture with confidence weighting

---

## Phase 1: Token Efficiency (P0)

### 1.1 Reduce SessionStart Injection

**Problem:** Current injection is ~3,000-4,000 tokens upfront.

**Solution:** Tiered injection with smart defaults.

| Tier | Content | Tokens | When |
|------|---------|--------|------|
| Always | Top 3 learnings (conf > 0.8) + handoff summary | ~500 | Every session |
| On-demand | Full search via MCP tools | ~50/query | When needed |
| Optional | Semantic context injection | ~200 | If FastEmbed available |

**Changes:**

```python
# hooks/session_start.py

# Before: 10 global + 10 project learnings
get_learnings_by_confidence(min_confidence=0.6, limit=10)

# After: Top 3 only, higher threshold
get_learnings_by_confidence(min_confidence=0.8, limit=3)
```

**Configuration** (`.claude/cortex-settings.json`):
```json
{
  "session_start": {
    "global_learning_limit": 3,
    "project_learning_limit": 3,
    "min_confidence": 0.8,
    "show_orchestration_guidance": false,
    "handoff_max_tokens": 200
  }
}
```

**Files to modify:**
- `hooks/session_start.py` - Reduce limits, add config loading
- `hooks/shared/handoff.py` - Add truncation option
- New: `.claude/cortex-settings.json` - Configuration schema

**Estimated savings:** 2,000-2,500 tokens per session

---

### 1.2 Make Orchestration Guidance Conditional

**Problem:** ~800 tokens of orchestration guidance injected every session.

**Solution:** Show only on first session or when explicitly requested.

**Implementation:**
```python
# hooks/session_start.py

def should_show_orchestration(project_dir: Path) -> bool:
    flag_file = project_dir / ".claude" / ".orchestration_shown"
    if not flag_file.exists():
        flag_file.touch()
        return True
    return False
```

**Files to modify:**
- `hooks/session_start.py` - Add conditional logic

**Estimated savings:** 800 tokens on subsequent sessions

---

## Phase 2: MCP Tools Integration (P0)

### 2.1 Create MCP Search Server

**Problem:** Current skill-based search has ~150ms latency (subprocess spawn).

**Solution:** STDIO-based MCP server with direct Python calls (~10ms).

**Architecture:**
```
Claude Code ←→ MCP Protocol (STDIO) ←→ mcp_server.py ←→ SearchIndex/Ledger
```

**New file:** `src/claude_cortex/mcp_server.py`

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
from claude_cortex.ledger import Ledger
from claude_cortex.search import SearchIndex

app = Server("claude-cortex")

@app.tool()
async def search_learnings(
    query: str,
    category: str = None,
    min_confidence: float = 0.5,
    limit: int = 10
) -> dict:
    """Search the knowledge ledger.

    Args:
        query: Full-text search query
        category: Filter by discovery/decision/error/pattern
        min_confidence: Minimum confidence threshold
        limit: Maximum results

    Returns:
        Matching learnings with IDs, snippets, and confidence scores
    """
    with SearchIndex(get_cache_dir()) as index:
        results = index.search(query, limit=limit)
        if category:
            results = [r for r in results if r.category == category]
    return {
        "results": [
            {"id": r.id[:8], "snippet": r.snippet, "confidence": r.confidence}
            for r in results
        ],
        "total": len(results)
    }

@app.tool()
async def get_learning(learning_id: str, show_outcomes: bool = False) -> dict:
    """Get full details of a learning by ID.

    Args:
        learning_id: Full or partial learning ID
        show_outcomes: Include outcome history

    Returns:
        Complete learning with content, metadata, and optionally outcomes
    """
    ledger = Ledger(get_ledger_path())
    learning, block = ledger.get_learning_by_id(learning_id, prefix_match=True)
    if not learning:
        return {"error": f"Learning '{learning_id}' not found"}

    result = {
        "id": learning.id,
        "category": learning.category.value,
        "content": learning.content,
        "confidence": learning.confidence,
        "source": learning.source,
        "created": block.timestamp.isoformat() if block else None
    }

    if show_outcomes:
        result["outcomes"] = ledger.get_learning_outcomes(learning.id)

    return result

@app.tool()
async def record_outcome(
    learning_id: str,
    result: str,
    comment: str = None
) -> dict:
    """Record outcome for a learning (updates confidence).

    Args:
        learning_id: Learning to update
        result: "success" | "partial" | "failure"
        comment: Optional context about the outcome

    Returns:
        Updated confidence score
    """
    if result not in ("success", "partial", "failure"):
        return {"error": "Result must be success, partial, or failure"}

    ledger = Ledger(get_ledger_path())
    ledger.record_outcome(learning_id, result, comment)
    return {
        "status": "recorded",
        "new_confidence": ledger.get_confidence(learning_id)
    }

@app.tool()
async def list_learnings(
    min_confidence: float = 0.5,
    category: str = None,
    limit: int = 20,
    show_decay: bool = False
) -> dict:
    """List learnings from the ledger.

    Args:
        min_confidence: Minimum confidence threshold
        category: Filter by category
        limit: Maximum results
        show_decay: Include effective confidence with decay

    Returns:
        List of learnings with metadata
    """
    ledger = Ledger(get_ledger_path())
    learnings = ledger.get_learnings_by_confidence(min_confidence, limit)

    return {
        "learnings": [
            {
                "id": l.id[:8],
                "category": l.category.value,
                "snippet": l.content[:100],
                "confidence": l.confidence,
                "effective_confidence": ledger.get_effective_confidence(l.id) if show_decay else None
            }
            for l in learnings
        ]
    }

if __name__ == "__main__":
    import asyncio
    asyncio.run(stdio_server(app))
```

**MCP Configuration** (`.mcp.json`):
```json
{
  "mcpServers": {
    "claude-cortex": {
      "command": "uv",
      "args": ["run", "python", "-m", "claude_cortex.mcp_server"],
      "cwd": "${CLAUDE_PLUGIN_ROOT}"
    }
  }
}
```

**Files to create/modify:**
- New: `src/claude_cortex/mcp_server.py` - MCP server implementation
- New: `.mcp.json` - MCP configuration
- `pyproject.toml` - Add `mcp` dependency
- `install.sh` - Register MCP server

**Dependencies:**
```toml
[project.dependencies]
mcp = ">=1.0.0"
```

---

## Phase 3: Privacy Controls (P1)

### 3.1 Tiered Privacy Tags

**Problem:** No way to mark learnings as private or project-scoped.

**Solution:** Tag suffixes for privacy levels.

**Syntax:**
```markdown
[DISCOVERY:private] API key format is ABC-XXX-...
[PATTERN:project] Our internal auth uses custom JWT claims
[ERROR] Standard error - can be shared globally
```

**Privacy levels:**
| Level | Behavior |
|-------|----------|
| `public` (default) | Normal learning, can be promoted |
| `project` | Stays in project ledger only |
| `private` | Captured but never persisted |
| `redacted` | Logged that something was redacted |

**Implementation:**

```python
# src/claude_cortex/ledger/models.py

class PrivacyLevel(str, Enum):
    PUBLIC = "public"
    PROJECT = "project"
    PRIVATE = "private"
    REDACTED = "redacted"

class Learning(BaseModel):
    # ... existing fields
    privacy: PrivacyLevel = PrivacyLevel.PUBLIC
```

```python
# hooks/shared/extraction.py

def parse_learning_tag(tag_content: str) -> tuple[str, str, PrivacyLevel]:
    """Parse [CATEGORY:privacy] content format."""
    match = re.match(r'\[(\w+)(?::(\w+))?\]\s*(.+)', tag_content)
    if match:
        category = match.group(1).lower()
        privacy = match.group(2) or "public"
        content = match.group(3)
        return category, content, PrivacyLevel(privacy)
    return None
```

**Files to modify:**
- `src/claude_cortex/ledger/models.py` - Add PrivacyLevel enum and field
- `hooks/shared/extraction.py` - Parse privacy suffix
- `src/claude_cortex/cli.py` - Filter in `promote` command
- `CLAUDE.md` - Document syntax

---

## Phase 4: Bun TUI Dashboard (P2)

### 4.1 Terminal Dashboard

**Problem:** No visual interface for viewing/managing learnings.

**Solution:** Bun-native TUI using `@hexie/tui` or `@opentui/core`.

**Why Bun:**
- Claude Code is built on Bun
- Native Bun TUI libraries available
- Fast startup, low memory
- Works over SSH (no browser needed)

**Library options:**

| Library | Pros | Cons |
|---------|------|------|
| `@hexie/tui` | Bun-native, zero deps, 60fps | Lower-level API |
| `@opentui/core` | Component-based, React reconciler | Requires Zig build |
| `ink` | React-like, mature ecosystem | Node.js focused |

**Recommended:** `@hexie/tui` for simplicity and Bun-native performance.

**Directory structure:**
```
tui/
├── package.json
├── tsconfig.json
├── src/
│   ├── index.ts          # Entry point
│   ├── components/
│   │   ├── LearningList.ts
│   │   ├── SearchBar.ts
│   │   ├── LearningDetail.ts
│   │   └── Dashboard.ts
│   └── api/
│       └── ledger.ts     # Calls Python CLI or MCP
```

**Features:**
- List learnings with search/filter
- View learning details
- Record outcomes interactively
- Show confidence decay visualization
- Keyboard navigation (vim-style)

**CLI integration:**
```bash
# Launch TUI
cclaude tui

# Or via bun directly
bun run tui
```

**Implementation approach:**
1. Create separate `tui/` directory with Bun project
2. Communicate with Python backend via:
   - Option A: Shell out to `cclaude` CLI
   - Option B: MCP client connection
   - Option C: Simple HTTP API (FastAPI)
3. Keep TUI optional (not required for core functionality)

---

## Phase 5: Hybrid Learning Capture (P1)

### 5.1 Confidence-Weighted Extraction

**Problem:** Single confidence for all learnings regardless of source.

**Solution:** Different default confidence by capture method.

| Source | Default Confidence | Rationale |
|--------|-------------------|-----------|
| User-tagged `[DISCOVERY]` etc | 0.70 | User validated |
| Stop hook pattern detection | 0.50 | System detected |
| LLM session analysis | 0.40 | AI extracted |
| Consensus (multiple sources) | 0.85 | Cross-validated |

**Implementation:**

```python
# hooks/shared/extraction.py

class ExtractionSource(str, Enum):
    USER_TAGGED = "user_tagged"
    STOP_HOOK = "stop_hook"
    LLM_ANALYSIS = "llm_analysis"
    CONSENSUS = "consensus"

DEFAULT_CONFIDENCE = {
    ExtractionSource.USER_TAGGED: 0.70,
    ExtractionSource.STOP_HOOK: 0.50,
    ExtractionSource.LLM_ANALYSIS: 0.40,
    ExtractionSource.CONSENSUS: 0.85,
}
```

### 5.2 Optional LLM Analysis (Background)

**Problem:** LLM analysis adds latency and cost to every session.

**Solution:** Run LLM analysis as optional background task.

**Trigger conditions:**
- Tagged learning count < 3 (user didn't tag much)
- Session duration > 30 minutes (significant work)
- User explicitly requests: `[ANALYZE_SESSION]`

**Implementation:**
```python
# hooks/session_end.py

async def maybe_run_llm_analysis(transcript: str, session_id: str):
    """Run LLM analysis if conditions met."""
    tagged_count = count_tagged_learnings(transcript)

    if tagged_count >= 3:
        return  # User tagged enough, skip LLM

    # Run in background, merge results later
    insights = await analyze_with_claude(transcript)
    for insight in insights:
        if not is_duplicate(insight):
            store_learning(
                insight,
                confidence=0.4,
                source="llm-analysis"
            )
```

---

## Implementation Order

### Sprint 1: Token Efficiency + MCP (Week 1)
- [ ] Reduce SessionStart injection limits
- [ ] Add configuration file support
- [ ] Make orchestration conditional
- [ ] Create MCP server with search tools
- [ ] Add `.mcp.json` configuration
- [ ] Update install.sh

### Sprint 2: Privacy + Capture (Week 2)
- [ ] Add PrivacyLevel to Learning model
- [ ] Parse privacy suffix in extraction
- [ ] Filter private learnings from promotion
- [ ] Implement confidence weighting by source
- [ ] Add optional LLM analysis flag

### Sprint 3: TUI Dashboard (Week 3)
- [ ] Set up Bun project in `tui/`
- [ ] Implement basic learning list view
- [ ] Add search/filter functionality
- [ ] Add outcome recording
- [ ] Integrate with CLI/MCP
- [ ] Add to install.sh

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                         CLAUDE-CORTEX 2.0                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐              │
│  │ SessionStart │    │  MCP Server  │    │   Bun TUI    │              │
│  │  (minimal)   │    │   (STDIO)    │    │  (optional)  │              │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘              │
│         │                   │                   │                       │
│         ▼                   ▼                   ▼                       │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    PYTHON CORE LIBRARY                           │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │   │
│  │  │   Ledger    │  │ SearchIndex │  │  Handoffs   │              │   │
│  │  │ (blockchain)│  │ (FTS5+vec)  │  │ (WIP state) │              │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘              │   │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │   │
│  │  │ Confidence  │  │   Privacy   │  │  Outcomes   │              │   │
│  │  │   Decay     │  │   Filters   │  │  Tracking   │              │   │
│  │  └─────────────┘  └─────────────┘  └─────────────┘              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                       HOOKS LAYER                                │   │
│  │  SessionStart │ Stop │ PreCompact │ SessionEnd │ SubagentStop   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Comparison: Claude-Cortex vs Claude-Mem

| Dimension | Claude-Mem | Claude-Cortex 2.0 |
|-----------|------------|-------------------|
| **Storage** | Plain SQLite | Blockchain + Merkle + Ed25519 |
| **Token efficiency** | 3-layer HTTP | Smart injection + MCP STDIO |
| **Service model** | Persistent worker (PM2) | On-demand STDIO |
| **Confidence** | Equal for all | Decay + reinforcement + source weighting |
| **Privacy** | Binary (private/not) | Tiered (public/project/private/redacted) |
| **Capture** | All observations | Hybrid with confidence weighting |
| **UI** | React web (localhost:37777) | Bun TUI (terminal-native) |
| **Dependencies** | Bun + PM2 + React + Chroma | Python + optional Bun TUI |
| **Portability** | Requires localhost port | Works over SSH |

---

## References

- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [Claude Code MCP Docs](https://code.claude.com/docs/en/mcp)
- [Effective Context Engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [@hexie/tui - Bun TUI Library](https://github.com/pyboosted/tui)
- [OpenTUI](https://github.com/sst/opentui)
- [Eliminating Token Bloat in MCP](https://glama.ai/blog/2025-12-14-code-execution-with-mcp-architecting-agentic-efficiency)
