# Contributing to Claude Cortex

Thank you for your interest in contributing to Claude Cortex! This document outlines how to contribute effectively.

## How to Contribute

### Reporting Issues

- Check existing issues before creating a new one
- Include reproduction steps, expected vs actual behavior
- For bugs, include Python version and OS

### Submitting Changes

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/claude-cortex.git
   cd claude-cortex
   ```
3. **Set up development environment**:
   ```bash
   uv sync
   ```
4. **Create a feature branch**:
   ```bash
   git checkout -b feat/your-feature-name
   ```
5. **Make your changes** and write tests
6. **Run tests** to ensure nothing breaks:
   ```bash
   uv run pytest tests/ -v
   ```
7. **Commit with conventional commit format**:
   ```bash
   git commit -m "feat(scope): add new feature"
   ```
8. **Push to your fork**:
   ```bash
   git push origin feat/your-feature-name
   ```
9. **Open a Pull Request** against `master`

## Development Setup

### Requirements

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) for package management
- [gh CLI](https://cli.github.com/) (optional, for PR ingestion features)

### Install Dependencies

```bash
# Clone and install
git clone https://github.com/YOUR_USERNAME/claude-cortex.git
cd claude-cortex
uv sync

# Verify installation
uv run cclaude --help
uv run pytest tests/ -v
```

### Running Tests

```bash
# Run all tests
uv run pytest tests/ -v

# Run specific test file
uv run pytest tests/test_ledger.py -v

# Run with coverage (if pytest-cov installed)
uv run pytest tests/ --cov=src/claude_cortex
```

## Code Style

### General Guidelines

- Keep changes focused and minimal
- Don't add features beyond what's requested
- Prefer editing existing files over creating new ones
- Add tests for new functionality

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
type(scope): description

[optional body]
```

**Types:**
- `feat` - New feature
- `fix` - Bug fix
- `docs` - Documentation only
- `refactor` - Code change that neither fixes a bug nor adds a feature
- `test` - Adding or updating tests
- `chore` - Maintenance tasks

**Examples:**
```
feat(entities): add Go language support for entity extraction
fix(ledger): handle concurrent writes with file locking
docs: update installation instructions for Windows
test(search): add FTS5 edge case tests
```

### Python Style

- Follow PEP 8
- Use type hints for function signatures
- Use `logging` module instead of `print()`
- Keep functions focused and small

## Project Structure

```
src/claude_cortex/
├── ledger/          # Blockchain ledger implementation
├── entities/        # Code entity graph (tree-sitter)
├── ingest/          # Git/PR learning ingestion
├── search/          # Full-text and semantic search
├── runner/          # Continuous execution mode
├── handoff/         # Session handoff management
├── summaries/       # Session summary storage
├── suggestions/     # Cross-project recommendations
├── analysis/        # LLM-powered session analysis
└── cli.py           # Command-line interface

tests/               # Test suite (pytest)
hooks/               # Claude Code hook scripts
agents/              # Custom agent definitions
skills/              # User-invocable skills
```

## Pull Request Guidelines

- Keep PRs focused on a single change
- Update documentation if behavior changes
- Add tests for new functionality
- Ensure all tests pass before requesting review
- Link related issues in the PR description

## Questions?

Open an issue for questions about contributing. We're happy to help!
