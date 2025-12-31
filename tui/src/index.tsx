#!/usr/bin/env bun
/**
 * Claude Cortex TUI Dashboard
 *
 * A terminal user interface for browsing and managing learnings
 * in the Claude Cortex ledger system.
 *
 * Usage:
 *   bun run tui/src/index.tsx [options]
 *   cclaude tui [options]
 *
 * Options:
 *   -p, --project <path>  Project directory (default: current directory)
 *   -h, --help            Show help message
 */

import React from "react";
import { render } from "ink";
import { Dashboard } from "./views/Dashboard.js";

// Parse command line arguments
function parseArgs(args: string[]): { projectPath?: string; help?: boolean } {
  const result: { projectPath?: string; help?: boolean } = {};

  for (let i = 0; i < args.length; i++) {
    const arg = args[i];

    if (arg === "-h" || arg === "--help") {
      result.help = true;
    } else if (arg === "-p" || arg === "--project") {
      result.projectPath = args[++i];
    } else if (arg.startsWith("--project=")) {
      result.projectPath = arg.split("=")[1];
    }
  }

  return result;
}

// Show help message
function showHelp(): void {
  console.log(`
Claude Cortex TUI Dashboard

A terminal user interface for browsing and managing learnings
in the Claude Cortex ledger system.

USAGE:
  bun run tui/src/index.tsx [options]
  cclaude tui [options]

OPTIONS:
  -p, --project <path>  Project directory (default: current directory)
  -h, --help            Show this help message

KEYBOARD SHORTCUTS:

  Navigation (Vim-style):
    j / Down Arrow    Move down in list
    k / Up Arrow      Move up in list
    g                 Jump to first item
    G                 Jump to last item
    Enter             View selected item details
    Esc               Go back / close

  Views:
    l                 Show list view (from detail)
    /                 Open search
    Tab               Toggle search input focus

  Actions:
    r                 Refresh data
    q                 Quit application

EXAMPLES:
  # Start TUI for current project
  bun run tui/src/index.tsx

  # Start TUI for specific project
  bun run tui/src/index.tsx -p ~/projects/myapp

  # Start via cclaude CLI (if integrated)
  cclaude tui
`);
}

// Main entry point
async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));

  if (args.help) {
    showHelp();
    process.exit(0);
  }

  // Clear screen and hide cursor for clean TUI experience
  process.stdout.write("\x1b[2J\x1b[H");

  // Render the dashboard
  const { waitUntilExit } = render(
    <Dashboard projectPath={args.projectPath} />,
    {
      // Exit on Ctrl+C
      exitOnCtrlC: true,
    }
  );

  try {
    await waitUntilExit();
  } finally {
    // Show cursor again
    process.stdout.write("\x1b[?25h");
    // Clear any remaining artifacts
    console.log("");
  }
}

// Run the application
main().catch((error) => {
  console.error("Fatal error:", error);
  process.exit(1);
});
