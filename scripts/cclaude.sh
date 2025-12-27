#!/usr/bin/env bash
#
# cclaude - Continuous Claude Custom wrapper
# Blockchain-style ledger memory with performance-based reinforcement
#

set -e

VERSION="0.1.0"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LEDGER_DIR="${HOME}/.claude/ledger"
ITERATION_CONTEXT_FILE=".claude/iteration_context.md"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Default values
MAX_RUNS=0
MAX_COST=0
MAX_DURATION=0
PROMPT=""
ENABLE_COMMITS=true
DRY_RUN=false
COMPLETION_SIGNAL="CONTINUOUS_CLAUDE_PROJECT_COMPLETE"
COMPLETION_THRESHOLD=3

show_help() {
    cat << EOF
cclaude - Continuous Claude with blockchain-style ledger memory

USAGE:
    cclaude <command> [options]

COMMANDS:
    run         Run continuous Claude with a prompt
    list        List learnings from the ledger
    show        Show details of a specific learning
    outcome     Record an outcome for a learning
    promote     Promote high-confidence learnings to global
    verify      Verify ledger chain integrity
    help        Show this help message

RUN OPTIONS:
    -p, --prompt TEXT       Task description (required)
    -m, --max-runs N        Maximum iterations
    --max-cost N.NN         Maximum cost in USD
    --max-duration DURATION Maximum time (e.g., 2h, 30m, 1h30m)
    --disable-commits       Skip git commit workflow
    --dry-run               Simulate without running Claude
    --completion-signal     Phrase indicating completion
    --completion-threshold  Consecutive signals needed to stop

EXAMPLES:
    cclaude run -p "Add unit tests" -m 5
    cclaude run -p "Refactor auth" --max-cost 5.00
    cclaude run -p "Fix bugs" --max-duration 2h
    cclaude list --min-confidence 0.7
    cclaude outcome abc123 -r success -c "Used in refactor"

EOF
}

# Parse duration string (e.g., "2h30m") to seconds
parse_duration() {
    local input="$1"
    local seconds=0

    if [[ "$input" =~ ([0-9]+)h ]]; then
        seconds=$((seconds + ${BASH_REMATCH[1]} * 3600))
    fi
    if [[ "$input" =~ ([0-9]+)m ]]; then
        seconds=$((seconds + ${BASH_REMATCH[1]} * 60))
    fi
    if [[ "$input" =~ ([0-9]+)s ]]; then
        seconds=$((seconds + ${BASH_REMATCH[1]}))
    fi

    echo "$seconds"
}

format_duration() {
    local seconds=$1
    local hours=$((seconds / 3600))
    local minutes=$(((seconds % 3600) / 60))
    local secs=$((seconds % 60))

    if [ $hours -gt 0 ]; then
        printf "%dh %dm %ds" $hours $minutes $secs
    elif [ $minutes -gt 0 ]; then
        printf "%dm %ds" $minutes $secs
    else
        printf "%ds" $secs
    fi
}

# Detect project type
detect_project() {
    if [ -f "pyproject.toml" ]; then
        echo "python:uv"
    elif [ -f "package.json" ]; then
        if [ -f "bun.lockb" ]; then
            echo "node:bun"
        else
            echo "node:npm"
        fi
    else
        echo "unknown:unknown"
    fi
}

# Query ledger for high-confidence learnings (Python-based, no jq needed)
get_ledger_learnings() {
    python3 << 'PYTHON_SCRIPT'
import json
from pathlib import Path

def get_learnings(ledger_path, limit=10):
    reinforcements_file = ledger_path / "reinforcements.json"
    if not reinforcements_file.exists():
        return []

    try:
        data = json.loads(reinforcements_file.read_text())
        learnings = []
        for lid, info in data.get("learnings", {}).items():
            if info.get("confidence", 0) >= 0.5:
                learnings.append({
                    "id": lid[:8],
                    "category": info.get("category", "unknown"),
                    "confidence": info.get("confidence", 0)
                })

        learnings.sort(key=lambda x: x["confidence"], reverse=True)
        return learnings[:limit]
    except:
        return []

def get_learning_content(ledger_path, learning_id):
    blocks_dir = ledger_path / "blocks"
    if not blocks_dir.exists():
        return None

    for block_file in blocks_dir.glob("*.json"):
        try:
            block = json.loads(block_file.read_text())
            for learning in block.get("learnings", []):
                if learning.get("id", "").startswith(learning_id):
                    return learning.get("content", "")
        except:
            continue
    return None

# Check global ledger
global_ledger = Path.home() / ".claude" / "ledger"
global_learnings = get_learnings(global_ledger)

# Check project ledger
project_ledger = Path(".claude/ledger")
project_learnings = get_learnings(project_ledger) if project_ledger.exists() else []

output = []

if global_learnings:
    output.append("## Global Knowledge")
    for l in global_learnings[:5]:
        content = get_learning_content(global_ledger, l["id"])
        if content:
            output.append(f"- [{l['category']}] ({int(l['confidence']*100)}%): {content[:150]}")
    output.append("")

if project_learnings:
    output.append("## Project Knowledge")
    for l in project_learnings[:5]:
        content = get_learning_content(project_ledger, l["id"])
        if content:
            output.append(f"- [{l['category']}] ({int(l['confidence']*100)}%): {content[:150]}")
    output.append("")

print("\n".join(output))
PYTHON_SCRIPT
}

# Extract learnings from Claude output and save to ledger
extract_and_save_learnings() {
    local output="$1"
    local session_id="$2"

    python3 << PYTHON_SCRIPT
import json
import hashlib
import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

output = '''$output'''
session_id = "$session_id"

# Extract learnings using tags
patterns = {
    "discovery": r"\[DISCOVERY\]\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
    "decision": r"\[DECISION\]\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
    "error": r"\[ERROR\]\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
    "pattern": r"\[PATTERN\]\s*(.+?)(?=\[(?:DISCOVERY|DECISION|ERROR|PATTERN)\]|$)",
}

learnings = []
seen = set()

for category, pattern in patterns.items():
    matches = re.findall(pattern, output, re.DOTALL | re.IGNORECASE)
    for match in matches:
        content = re.sub(r"\s+", " ", match.strip())[:500]
        if content and len(content) > 20 and content not in seen:
            seen.add(content)
            learnings.append({
                "id": str(uuid4()),
                "category": category,
                "content": content,
                "confidence": 0.5,
                "source": None,
                "outcomes": []
            })

if not learnings:
    print("0")
    exit(0)

# Determine ledger path
project_markers = [".claude", "pyproject.toml", "package.json"]
cwd = Path.cwd()
is_project = any((cwd / m).exists() for m in project_markers)

if is_project:
    ledger_path = cwd / ".claude" / "ledger"
else:
    ledger_path = Path.home() / ".claude" / "ledger"

# Ensure structure
ledger_path.mkdir(parents=True, exist_ok=True)
(ledger_path / "blocks").mkdir(exist_ok=True)

index_file = ledger_path / "index.json"
if not index_file.exists():
    index_file.write_text('{"head": null, "blocks": []}')

reinforcements_file = ledger_path / "reinforcements.json"
if not reinforcements_file.exists():
    reinforcements_file.write_text('{"learnings": {}}')

# Read state
index = json.loads(index_file.read_text())
reinforcements = json.loads(reinforcements_file.read_text())

# Create block
block_id = str(uuid4())[:8]
block = {
    "id": block_id,
    "timestamp": datetime.utcnow().isoformat(),
    "session_id": session_id,
    "parent_block": index.get("head"),
    "learnings": learnings
}
block["hash"] = hashlib.sha256(json.dumps(block, sort_keys=True, default=str).encode()).hexdigest()

# Save
(ledger_path / "blocks" / f"{block_id}.json").write_text(json.dumps(block, indent=2))
index["head"] = block_id
index["blocks"].append({"id": block_id, "timestamp": block["timestamp"], "hash": block["hash"], "parent": block.get("parent_block")})
index_file.write_text(json.dumps(index, indent=2))

for learning in learnings:
    reinforcements["learnings"][learning["id"]] = {
        "category": learning["category"],
        "confidence": learning["confidence"],
        "outcome_count": 0,
        "last_updated": datetime.utcnow().isoformat()
    }
reinforcements_file.write_text(json.dumps(reinforcements, indent=2))

print(str(len(learnings)))
PYTHON_SCRIPT
}

# Build context for iteration
build_iteration_context() {
    local iteration=$1
    local context=""

    # Project type
    local project_info=$(detect_project)
    local project_type="${project_info%%:*}"
    local pkg_manager="${project_info##*:}"

    if [ "$project_type" != "unknown" ]; then
        context+="## Project Environment\n"
        context+="- Type: $project_type\n"
        context+="- Package manager: $pkg_manager\n\n"
    fi

    # Ledger knowledge (using Python, no jq)
    local ledger_context=$(get_ledger_learnings)
    if [ -n "$ledger_context" ]; then
        context+="$ledger_context\n"
    fi

    # Previous iteration context
    if [ -f "$ITERATION_CONTEXT_FILE" ]; then
        context+="## Previous Iteration Context\n"
        context+="$(cat "$ITERATION_CONTEXT_FILE")\n\n"
    fi

    # Learning capture instructions
    context+="## Knowledge Capture\n"
    context+="Document insights using these tags (they will be saved to the ledger):\n"
    context+="- [DISCOVERY] New information about the codebase\n"
    context+="- [DECISION] Architectural choices made\n"
    context+="- [ERROR] Mistakes or gotchas to avoid\n"
    context+="- [PATTERN] Reusable solutions identified\n\n"

    echo -e "$context"
}

# Run a single Claude iteration
run_iteration() {
    local iteration=$1
    local prompt="$2"
    local session_id="iter-$iteration-$(date +%s)"

    echo -e "${BLUE}==>${NC} Iteration $iteration"

    # Build context
    local context=$(build_iteration_context "$iteration")

    # Build full prompt
    local full_prompt="$context\n## Task\n$prompt\n\n## Instructions\nMake incremental progress on the task. After completing work:\n1. Tag any learnings with [DISCOVERY], [DECISION], [ERROR], or [PATTERN]\n2. Summarize what was done and what's next\n\nIf the task is complete, output: $COMPLETION_SIGNAL"

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}[DRY RUN]${NC} Would run Claude with prompt:"
        echo -e "$full_prompt"
        return 0
    fi

    # Ensure .claude directory exists for iteration context
    mkdir -p .claude

    # Run Claude and capture output
    local result
    local exit_code=0
    result=$(claude -p "$full_prompt" --output-format json 2>&1) || exit_code=$?

    if [ "$exit_code" -ne 0 ]; then
        echo -e "${RED}Claude failed with exit code $exit_code${NC}"
        return 1
    fi

    # Parse result
    local is_error=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('is_error', False))" 2>/dev/null || echo "False")
    local cost=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('total_cost_usd', 0))" 2>/dev/null || echo "0")
    local output=$(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('result', d.get('message', 'No output')))" 2>/dev/null || echo "No output")

    if [ "$is_error" = "True" ]; then
        echo -e "${RED}Claude returned an error${NC}"
        echo "$output"
        return 1
    fi

    echo -e "${GREEN}✓${NC} Completed (cost: \$$cost)"

    # Extract learnings and save to ledger
    local learning_count=$(extract_and_save_learnings "$output" "$session_id")
    if [ "$learning_count" -gt 0 ]; then
        echo -e "${CYAN}  └─ Extracted $learning_count learnings to ledger${NC}"
    fi

    # Save iteration context for next iteration
    echo "$output" | tail -50 > "$ITERATION_CONTEXT_FILE"

    # Check for completion signal
    if echo "$output" | grep -q "$COMPLETION_SIGNAL"; then
        echo -e "${CYAN}Completion signal detected${NC}"
        return 2
    fi

    # Commit changes if enabled
    if [ "$ENABLE_COMMITS" = true ]; then
        if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
            echo -e "${BLUE}Committing changes...${NC}"
            git add -A
            git commit -m "chore: iteration $iteration progress

🤖 Generated with continuous-claude-custom" || true
        fi
    fi

    echo "$cost"
}

# Main execution loop
run_continuous() {
    local start_time=$(date +%s)
    local total_cost=0
    local iteration=0
    local completion_count=0
    local consecutive_errors=0
    local total_learnings=0

    echo -e "${CYAN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║        Continuous Claude Custom - Starting                   ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "${BLUE}Prompt:${NC} $PROMPT"
    echo -e "${BLUE}Limits:${NC} runs=$MAX_RUNS, cost=\$$MAX_COST, duration=$(format_duration $MAX_DURATION)"
    echo ""

    while true; do
        iteration=$((iteration + 1))

        # Check limits
        if [ "$MAX_RUNS" -gt 0 ] && [ "$iteration" -gt "$MAX_RUNS" ]; then
            echo -e "${YELLOW}Reached maximum iterations ($MAX_RUNS)${NC}"
            break
        fi

        local elapsed=$(($(date +%s) - start_time))
        if [ "$MAX_DURATION" -gt 0 ] && [ "$elapsed" -ge "$MAX_DURATION" ]; then
            echo -e "${YELLOW}Reached maximum duration ($(format_duration $MAX_DURATION))${NC}"
            break
        fi

        if [ "$MAX_COST" != "0" ]; then
            local cost_check=$(python3 -c "print(1 if $total_cost >= $MAX_COST else 0)" 2>/dev/null || echo "0")
            if [ "$cost_check" = "1" ]; then
                echo -e "${YELLOW}Reached maximum cost (\$$MAX_COST)${NC}"
                break
            fi
        fi

        # Run iteration
        local result
        result=$(run_iteration "$iteration" "$PROMPT")
        local exit_code=$?

        if [ $exit_code -eq 2 ]; then
            completion_count=$((completion_count + 1))
            if [ "$completion_count" -ge "$COMPLETION_THRESHOLD" ]; then
                echo -e "${GREEN}✨ Project completed! (detected $completion_count times)${NC}"
                break
            fi
        elif [ $exit_code -ne 0 ]; then
            consecutive_errors=$((consecutive_errors + 1))
            if [ "$consecutive_errors" -ge 3 ]; then
                echo -e "${RED}Too many consecutive errors, stopping${NC}"
                break
            fi
        else
            consecutive_errors=0
            completion_count=0

            if [[ "$result" =~ ^[0-9.]+$ ]]; then
                total_cost=$(python3 -c "print($total_cost + $result)")
            fi
        fi

        sleep 1
    done

    local total_time=$(($(date +%s) - start_time))

    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║        Run Complete                                          ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════════════╝${NC}"
    echo -e "Iterations: $iteration"
    echo -e "Total cost: \$$(printf '%.4f' $total_cost)"
    echo -e "Duration:   $(format_duration $total_time)"

    # Show ledger stats
    echo ""
    echo -e "${BLUE}Ledger Status:${NC}"
    cd "$PROJECT_ROOT" && uv run cclaude verify 2>/dev/null || python3 -m continuous_claude.cli verify 2>/dev/null || echo "  (run 'cclaude verify' to check)"
}

# Command handlers
cmd_run() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            -p|--prompt)
                PROMPT="$2"
                shift 2
                ;;
            -m|--max-runs)
                MAX_RUNS="$2"
                shift 2
                ;;
            --max-cost)
                MAX_COST="$2"
                shift 2
                ;;
            --max-duration)
                MAX_DURATION=$(parse_duration "$2")
                shift 2
                ;;
            --disable-commits)
                ENABLE_COMMITS=false
                shift
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --completion-signal)
                COMPLETION_SIGNAL="$2"
                shift 2
                ;;
            --completion-threshold)
                COMPLETION_THRESHOLD="$2"
                shift 2
                ;;
            *)
                echo -e "${RED}Unknown option: $1${NC}"
                exit 1
                ;;
        esac
    done

    if [ -z "$PROMPT" ]; then
        echo -e "${RED}Error: --prompt is required${NC}"
        exit 1
    fi

    if [ "$MAX_RUNS" -eq 0 ] && [ "$MAX_COST" = "0" ] && [ "$MAX_DURATION" -eq 0 ]; then
        echo -e "${RED}Error: At least one limit (--max-runs, --max-cost, --max-duration) is required${NC}"
        exit 1
    fi

    run_continuous
}

cmd_list() {
    cd "$PROJECT_ROOT" && uv run python -m continuous_claude.cli list "$@"
}

cmd_show() {
    cd "$PROJECT_ROOT" && uv run python -m continuous_claude.cli show "$@"
}

cmd_outcome() {
    cd "$PROJECT_ROOT" && uv run python -m continuous_claude.cli outcome "$@"
}

cmd_promote() {
    cd "$PROJECT_ROOT" && uv run python -m continuous_claude.cli promote "$@"
}

cmd_verify() {
    cd "$PROJECT_ROOT" && uv run python -m continuous_claude.cli verify "$@"
}

main() {
    if [ $# -eq 0 ]; then
        show_help
        exit 0
    fi

    local command="$1"
    shift

    case "$command" in
        run)
            cmd_run "$@"
            ;;
        list)
            cmd_list "$@"
            ;;
        show)
            cmd_show "$@"
            ;;
        outcome)
            cmd_outcome "$@"
            ;;
        promote)
            cmd_promote "$@"
            ;;
        verify)
            cmd_verify "$@"
            ;;
        help|--help|-h)
            show_help
            ;;
        version|--version|-v)
            echo "cclaude version $VERSION"
            ;;
        *)
            echo -e "${RED}Unknown command: $command${NC}"
            echo "Run 'cclaude help' for usage"
            exit 1
            ;;
    esac
}

main "$@"
