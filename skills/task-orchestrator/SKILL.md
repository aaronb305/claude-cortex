---
name: task-orchestrator
description: Architectural decomposition and delegation strategy for complex tasks. Use when receiving broad requests like "improve", "add feature", "refactor", "build", or any multi-step implementation. Analyzes the problem, creates phased execution plan, identifies parallelization opportunities, and specifies which agents to deploy for each phase. **Complexity indicator**: Strategic planning for orchestration. For actual execution coordination, deploy the `continuous-runner` agent.
allowed-tools: Read, Glob, Grep
---

# Task Orchestrator Skill

This skill helps decompose complex requests into actionable phases with appropriate agent delegation.

## When to Use

Trigger on broad or complex requests:
- "Improve X", "Optimize Y", "Enhance Z"
- "Add feature X", "Implement Y", "Build Z"
- "Refactor X", "Clean up Y", "Modernize Z"
- "Fix all issues in X", "Review and improve Y"
- Any task requiring 3+ steps or multiple file changes

## Decomposition Framework

### Phase 1: Understand (Research)

**Purpose**: Gather context before acting

**Deploy**: `research-agent` (can run multiple in parallel)

| Pattern | Agent Task |
|---------|-----------|
| "improve X" | Research current X implementation, identify weaknesses |
| "add feature" | Research existing patterns, find integration points |
| "refactor" | Map current architecture, identify dependencies |
| "fix issues" | Investigate root causes, categorize by severity |

**Parallelization**: Yes - deploy multiple research-agents for different aspects

### Phase 2: Plan (Architecture)

**Purpose**: Design solution before implementing

**Output**: Structured plan with:
- Files to create/modify
- Dependencies between changes
- Test requirements
- Risk areas

**Example Plan Format**:
```markdown
## Implementation Plan: [Feature Name]

### Wave 1 (Parallel)
- [ ] research-agent: Analyze existing auth patterns
- [ ] research-agent: Check API rate limiting requirements

### Wave 2 (Parallel - after Wave 1)
- [ ] code-implementer: Create auth middleware
- [ ] test-writer: Write auth tests (parallel with above)

### Wave 3 (Sequential - needs Wave 2)
- [ ] code-implementer: Integrate into routes
- [ ] doc-writer: Update API documentation

### Verification
- [ ] Run test suite
- [ ] Manual verification points
```

### Phase 3: Execute (Implementation)

**Deploy based on task type**:

| Task Type | Primary Agent | Parallel Agent |
|-----------|--------------|----------------|
| New code | `code-implementer` | `test-writer` |
| Bug fix | `bug-investigator` | `test-writer` |
| Refactor | `refactorer` | `test-writer` |
| Documentation | `doc-writer` | - |
| Research | `research-agent` | - |

**Parallelization Rules**:
- `code-implementer` + `test-writer` = Yes (TDD style)
- `code-implementer` + `code-implementer` = Only if different files
- `bug-investigator` + `test-writer` = Yes (reproduce while investigating)

### Phase 4: Verify (Quality)

**Deploy**: Verification agents after implementation

| Check | Agent |
|-------|-------|
| Tests pass | `test-writer` (run tests) |
| Code review | Built-in review (no agent needed) |
| Documentation | `doc-writer` (verify completeness) |

## Agent Capabilities Reference

### Execution Agents (Focused Work)

| Agent | Best For | Tools |
|-------|----------|-------|
| `code-implementer` | Writing/modifying specific code | Read, Write, Edit, Bash, Glob, Grep |
| `test-writer` | Creating test files, running tests | Read, Write, Edit, Bash, Glob, Grep |
| `research-agent` | Investigation, pattern discovery | Read, Grep, Glob, Bash, WebSearch, WebFetch |
| `refactorer` | Code restructuring | Read, Write, Edit, Bash, Glob, Grep |
| `bug-investigator` | Debugging, root cause analysis | Read, Bash, Grep, Glob, Edit |
| `doc-writer` | Documentation creation/updates | Read, Write, Edit, Glob, Grep |

### Coordination Agents (Workflows)

| Agent | Best For |
|-------|----------|
| `continuous-runner` | Long-running autonomous sessions |
| `knowledge-retriever` | Deep search across learnings |
| `session-continuity` | Session restoration |
| `learning-extractor` | Extract insights from conversations |
| `outcome-tracker` | Record outcomes for learnings |

## Decision Matrix

```
Is it a single, simple task?
├─ YES → Do it directly (no agents)
└─ NO → Does it require research first?
    ├─ YES → Deploy research-agent(s) first
    └─ NO → Can tasks run in parallel?
        ├─ YES → Deploy multiple agents simultaneously
        └─ NO → Deploy sequentially with dependencies
```

## Example Decompositions

### "Improve the authentication system"

```
Phase 1: Understand
├─ research-agent: "Analyze current auth implementation"
├─ research-agent: "Find auth best practices in codebase"

Phase 2: Plan
├─ Identify: password hashing, session management, token handling
├─ Prioritize: security > performance > maintainability

Phase 3: Execute (Wave 1 - Parallel)
├─ code-implementer: "Upgrade password hashing to bcrypt"
├─ test-writer: "Add password security tests"

Phase 3: Execute (Wave 2 - Sequential)
├─ code-implementer: "Implement refresh token rotation"
├─ test-writer: "Add refresh token tests"

Phase 4: Verify
├─ Run full test suite
├─ Security review
```

### "Add user notification feature"

```
Phase 1: Understand
├─ research-agent: "How do existing features notify users?"
├─ research-agent: "What notification channels exist?"

Phase 2: Plan
├─ Components: NotificationService, templates, preferences
├─ Integration: user settings, event triggers

Phase 3: Execute (Wave 1 - Parallel)
├─ code-implementer: "Create NotificationService class"
├─ code-implementer: "Create notification templates" (different files)
├─ test-writer: "Write notification service tests"

Phase 3: Execute (Wave 2)
├─ code-implementer: "Integrate with user preferences"
├─ doc-writer: "Document notification API"

Phase 4: Verify
├─ Integration tests
├─ Manual notification test
```

### "Fix performance issues in the API"

```
Phase 1: Understand
├─ research-agent: "Profile API endpoints for bottlenecks"
├─ research-agent: "Analyze database query patterns"

Phase 2: Plan
├─ Categorize: N+1 queries, missing indexes, inefficient algorithms
├─ Prioritize by impact

Phase 3: Execute (Sequential - careful with performance)
├─ bug-investigator: "Confirm root cause of slowest endpoint"
├─ code-implementer: "Add database indexes"
├─ code-implementer: "Fix N+1 queries with eager loading"
├─ test-writer: "Add performance regression tests"

Phase 4: Verify
├─ Run benchmarks
├─ Compare before/after metrics
```

## Continuous Progress Tracking

Throughout execution:
1. Use `TodoWrite` to track all phases and tasks
2. Mark tasks `in_progress` when agents are deployed
3. Mark tasks `completed` when agents return
4. Add newly discovered tasks as they emerge
5. Update handoff if session may end

## Anti-Patterns to Avoid

1. **Over-decomposition**: Don't create 20 agents for a 3-file change
2. **Sequential when parallel possible**: Deploy independent agents together
3. **Skipping research**: Complex tasks benefit from understanding first
4. **No verification**: Always run tests after implementation
5. **Ignoring dependencies**: Don't parallelize when outputs feed inputs

## Integration with Ledger

After completing complex tasks:
1. Tag discoveries: `[DISCOVERY] Found X pattern in codebase`
2. Tag decisions: `[DECISION] Chose Y approach because Z`
3. Tag errors: `[ERROR] Avoid X when doing Y`
4. Tag patterns: `[PATTERN] For similar tasks, use this structure`
