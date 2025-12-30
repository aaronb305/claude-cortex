#!/usr/bin/env bash
#
# Continuous Claude Custom - Installation Script
# Blockchain-style ledger memory with performance-based reinforcement
#

set -e

INSTALL_DIR="${HOME}/.local/bin"
HOOKS_DIR="${HOME}/.claude/hooks"
LEDGER_DIR="${HOME}/.claude/ledger"
SETTINGS_FILE="${HOME}/.claude/settings.json"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

print_step() {
    echo -e "${BLUE}==>${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}!${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# Check for required commands
check_requirements() {
    print_step "Checking requirements..."

    local missing=()

    if ! command -v claude &> /dev/null; then
        missing+=("claude (Claude Code CLI)")
    fi

    if ! command -v python3 &> /dev/null; then
        missing+=("python3")
    fi

    if ! command -v uv &> /dev/null; then
        print_warning "uv not found - recommended for Python projects"
    fi

    if ! command -v jq &> /dev/null; then
        print_warning "jq not found - settings.json merge will be skipped"
        print_warning "Install jq for automatic hook configuration"
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        print_error "Missing required dependencies:"
        for dep in "${missing[@]}"; do
            echo "  - $dep"
        done
        echo ""
        echo "Please install missing dependencies and try again."
        exit 1
    fi

    print_success "All requirements met"
}

# Create directory structure
create_directories() {
    print_step "Creating directory structure..."

    mkdir -p "$INSTALL_DIR"
    mkdir -p "$HOOKS_DIR"
    mkdir -p "$LEDGER_DIR/blocks"
    mkdir -p "${HOME}/.claude/settings.local.d"

    print_success "Directories created"
}

# Install Python package
install_python_package() {
    print_step "Installing Python package..."

    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    # Check if we're running from the repo
    if [ -f "$script_dir/pyproject.toml" ]; then
        print_step "Installing from local source..."
        cd "$script_dir"

        if command -v uv &> /dev/null; then
            # Use uv to sync the project (creates venv if needed)
            uv sync
            print_success "Python package installed (use 'uv run cclaude' or activate venv)"
        else
            pip3 install --user -e .
            print_success "Python package installed"
        fi
    else
        print_warning "Local source not found, skipping Python package install"
        print_warning "Clone the repo and run install.sh from within it"
    fi
}

# Install hook scripts
install_hooks() {
    print_step "Installing hook scripts..."

    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    # Copy hook scripts
    if [ -d "$script_dir/hooks" ]; then
        cp "$script_dir/hooks/"*.py "$HOOKS_DIR/" 2>/dev/null || true
        cp "$script_dir/hooks/"*.sh "$HOOKS_DIR/" 2>/dev/null || true
        chmod +x "$HOOKS_DIR/"*.py 2>/dev/null || true
        chmod +x "$HOOKS_DIR/"*.sh 2>/dev/null || true
        print_success "Hook scripts installed to $HOOKS_DIR"
    else
        print_warning "No hooks directory found in source"
    fi
}

# Configure Claude Code settings
configure_settings() {
    print_step "Configuring Claude Code settings..."

    # Create settings if it doesn't exist
    if [ ! -f "$SETTINGS_FILE" ]; then
        echo '{}' > "$SETTINGS_FILE"
    fi

    # Check if jq is available
    if ! command -v jq &> /dev/null; then
        print_warning "jq not installed - skipping automatic settings configuration"
        print_warning "Please manually add hooks to $SETTINGS_FILE:"
        echo ""
        echo '  "hooks": {'
        echo '    "SessionStart": [{"hooks": [{"type": "command", "command": "'"$HOOKS_DIR"'/session_start.py"}]}],'
        echo '    "SessionEnd": [{"hooks": [{"type": "command", "command": "'"$HOOKS_DIR"'/session_end.py"}]}],'
        echo '    "PreCompact": [{"hooks": [{"type": "command", "command": "'"$HOOKS_DIR"'/pre_compact.py"}]}],'
        echo '    "PostToolUse": [{"hooks": [{"type": "command", "command": "'"$HOOKS_DIR"'/post_tool_use.py"}]}],'
        echo '    "Stop": [{"hooks": [{"type": "command", "command": "'"$HOOKS_DIR"'/stop.py"}]}]'
        echo '  }'
        echo ""
        return
    fi

    # Backup existing settings
    cp "$SETTINGS_FILE" "${SETTINGS_FILE}.backup"

    # Add hooks configuration using jq
    local hooks_config='{
        "hooks": {
            "SessionStart": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "'"$HOOKS_DIR"'/session_start.py"
                        }
                    ]
                }
            ],
            "SessionEnd": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "'"$HOOKS_DIR"'/session_end.py"
                        }
                    ]
                }
            ],
            "PreCompact": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "'"$HOOKS_DIR"'/pre_compact.py"
                        }
                    ]
                }
            ],
            "PostToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "'"$HOOKS_DIR"'/post_tool_use.py"
                        }
                    ]
                }
            ],
            "Stop": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": "'"$HOOKS_DIR"'/stop.py"
                        }
                    ]
                }
            ]
        }
    }'

    # Merge with existing settings
    local current_settings=$(cat "$SETTINGS_FILE")

    if echo "$current_settings" | jq -e '.hooks' > /dev/null 2>&1; then
        print_warning "Hooks already configured in settings.json"
        print_warning "Please manually add continuous-claude-custom hooks if needed"
        print_warning "See: $HOOKS_DIR for hook scripts"
    else
        echo "$current_settings" | jq ". + $hooks_config" > "$SETTINGS_FILE"
        print_success "Hooks configured in settings.json"
    fi
}

# Initialize global ledger
init_ledger() {
    print_step "Initializing global ledger..."

    if [ ! -f "$LEDGER_DIR/index.json" ]; then
        echo '{"head": null, "blocks": []}' > "$LEDGER_DIR/index.json"
    fi

    if [ ! -f "$LEDGER_DIR/reinforcements.json" ]; then
        echo '{"learnings": {}}' > "$LEDGER_DIR/reinforcements.json"
    fi

    print_success "Global ledger initialized at $LEDGER_DIR"
}

# Install wrapper script
install_wrapper() {
    print_step "Installing cclaude wrapper..."

    local script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

    if [ -f "$script_dir/scripts/cclaude.sh" ]; then
        cp "$script_dir/scripts/cclaude.sh" "$INSTALL_DIR/cclaude"
        chmod +x "$INSTALL_DIR/cclaude"
        print_success "Wrapper script installed to $INSTALL_DIR/cclaude"
    else
        print_warning "Wrapper script not found, using Python CLI"
    fi
}

# Check PATH
check_path() {
    if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
        print_warning "$INSTALL_DIR is not in your PATH"
        echo ""
        echo "Add this to your shell profile (~/.bashrc, ~/.zshrc, etc.):"
        echo ""
        echo "  export PATH=\"\$PATH:$INSTALL_DIR\""
        echo ""
    fi
}

# Print usage info
print_usage() {
    echo ""
    echo -e "${GREEN}Installation complete!${NC}"
    echo ""
    echo "Usage:"
    echo ""
    echo "  # Just use Claude normally - hooks add ledger context automatically"
    echo "  claude"
    echo ""
    echo "  # Run in continuous mode (like continuous-claude)"
    echo "  cclaude run \"your task\" --max-runs 5"
    echo ""
    echo "  # List learnings from the ledger"
    echo "  cclaude list --min-confidence 0.7"
    echo ""
    echo "  # Record an outcome (adjusts confidence)"
    echo "  cclaude outcome <id> -r success -c \"context\""
    echo ""
    echo "  # Verify ledger integrity"
    echo "  cclaude verify"
    echo ""
    echo "Ledger location: $LEDGER_DIR"
    echo "Hooks location:  $HOOKS_DIR"
    echo ""
}

# Main installation
main() {
    echo ""
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║        Continuous Claude Custom - Installation               ║"
    echo "║   Blockchain-style ledger memory with reinforcement          ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""

    check_requirements
    create_directories
    install_python_package
    install_hooks
    configure_settings
    init_ledger
    install_wrapper
    check_path
    print_usage
}

main "$@"
