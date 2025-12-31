# Claude Cortex TUI Dashboard

A terminal user interface for browsing and managing learnings in the Claude Cortex ledger system.

## Features

- **Learning List**: Browse all learnings with color-coded categories and confidence bars
- **Learning Detail**: View full learning content, metadata, and confidence information
- **Search**: Real-time search with filtering across all learnings
- **Vim-style Navigation**: Use `j`/`k` keys for navigation, `/` for search

## Installation

```bash
cd tui
bun install
```

## Usage

```bash
# Start TUI for current project
bun run tui

# Or run directly
bun run src/index.tsx

# Start TUI for specific project
bun run tui -p ~/projects/myapp
```

## Keyboard Shortcuts

### Navigation (Vim-style)
| Key | Action |
|-----|--------|
| `j` / `Down Arrow` | Move down in list |
| `k` / `Up Arrow` | Move up in list |
| `g` | Jump to first item |
| `G` | Jump to last item |
| `Enter` | View selected item details |
| `Esc` | Go back / close |

### Views
| Key | Action |
|-----|--------|
| `l` | Show list view (from detail) |
| `/` | Open search |
| `Tab` | Toggle search input focus |

### Actions
| Key | Action |
|-----|--------|
| `r` | Refresh data |
| `q` | Quit application |

## Architecture

```
tui/
├── package.json           # Bun package configuration
├── tsconfig.json          # TypeScript configuration
└── src/
    ├── index.tsx          # Entry point
    ├── api.ts             # Python CLI integration
    ├── views/
    │   ├── Dashboard.tsx  # Main dashboard layout
    │   ├── LearningList.tsx
    │   ├── LearningDetail.tsx
    │   └── Search.tsx
    └── utils/
        └── format.ts      # Formatting helpers
```

## Dependencies

- **ink**: React for interactive command-line apps
- **ink-text-input**: Text input component for Ink
- **ink-spinner**: Loading spinner for Ink
- **react**: React framework

## Integration

The TUI integrates with the Python CLI (`cclaude`) via the `api.ts` module:
- `listLearnings()`: Fetches learnings from the ledger
- `searchLearnings()`: Searches learnings by query
- `getLearning()`: Gets a single learning by ID
- `getStats()`: Gets ledger statistics

## Development

```bash
# Run in development mode
bun run dev

# Type check
bun run typecheck

# Build for production
bun run build
```
