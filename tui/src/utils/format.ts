/**
 * Formatting utilities for the TUI dashboard
 */

// ANSI color codes for terminal output
export const colors = {
  // Category colors
  discovery: "\x1b[36m", // Cyan
  decision: "\x1b[33m", // Yellow
  error: "\x1b[31m", // Red
  pattern: "\x1b[35m", // Magenta

  // Status colors
  success: "\x1b[32m", // Green
  warning: "\x1b[33m", // Yellow
  danger: "\x1b[31m", // Red
  info: "\x1b[34m", // Blue

  // UI colors
  muted: "\x1b[90m", // Gray
  highlight: "\x1b[97m", // Bright white
  accent: "\x1b[96m", // Bright cyan

  // Reset
  reset: "\x1b[0m",
};

// Box drawing characters
export const box = {
  topLeft: "\u250c",
  topRight: "\u2510",
  bottomLeft: "\u2514",
  bottomRight: "\u2518",
  horizontal: "\u2500",
  vertical: "\u2502",
  leftT: "\u251c",
  rightT: "\u2524",
  topT: "\u252c",
  bottomT: "\u2534",
  cross: "\u253c",
};

// Heavy box drawing
export const heavyBox = {
  topLeft: "\u250f",
  topRight: "\u2513",
  bottomLeft: "\u2517",
  bottomRight: "\u251b",
  horizontal: "\u2501",
  vertical: "\u2503",
};

// Double line box drawing
export const doubleBox = {
  topLeft: "\u2554",
  topRight: "\u2557",
  bottomLeft: "\u255a",
  bottomRight: "\u255d",
  horizontal: "\u2550",
  vertical: "\u2551",
};

/**
 * Format a confidence value as a colored bar
 */
export function formatConfidenceBar(
  confidence: number,
  width: number = 20
): string {
  const filled = Math.round(confidence * width);
  const empty = width - filled;

  // Choose color based on confidence level
  let color: string;
  if (confidence >= 0.8) {
    color = colors.success;
  } else if (confidence >= 0.5) {
    color = colors.warning;
  } else {
    color = colors.danger;
  }

  const filledChar = "\u2588"; // Full block
  const emptyChar = "\u2591"; // Light shade

  return `${color}${filledChar.repeat(filled)}${colors.muted}${emptyChar.repeat(empty)}${colors.reset}`;
}

/**
 * Format confidence as percentage with color
 */
export function formatConfidencePercent(confidence: number): string {
  const percent = Math.round(confidence * 100);

  let color: string;
  if (confidence >= 0.8) {
    color = colors.success;
  } else if (confidence >= 0.5) {
    color = colors.warning;
  } else {
    color = colors.danger;
  }

  return `${color}${percent}%${colors.reset}`;
}

/**
 * Format a category with its color
 */
export function formatCategory(
  category: "discovery" | "decision" | "error" | "pattern"
): string {
  const color = colors[category] || colors.muted;
  const icon = getCategoryIcon(category);
  return `${color}${icon} ${category.toUpperCase()}${colors.reset}`;
}

/**
 * Get icon for category
 */
export function getCategoryIcon(category: string): string {
  switch (category) {
    case "discovery":
      return "\u2605"; // Star
    case "decision":
      return "\u2713"; // Check mark
    case "error":
      return "\u2717"; // X mark
    case "pattern":
      return "\u2261"; // Three horizontal lines
    default:
      return "\u2022"; // Bullet
  }
}

/**
 * Truncate text to max length with ellipsis
 */
export function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength - 3) + "...";
}

/**
 * Wrap text to specified width
 */
export function wrapText(text: string, width: number): string[] {
  const words = text.split(/\s+/);
  const lines: string[] = [];
  let currentLine = "";

  for (const word of words) {
    if (currentLine.length + word.length + 1 <= width) {
      currentLine += (currentLine ? " " : "") + word;
    } else {
      if (currentLine) lines.push(currentLine);
      currentLine = word;
    }
  }

  if (currentLine) lines.push(currentLine);
  return lines;
}

/**
 * Format a timestamp as relative time
 */
export function formatRelativeTime(timestamp: string): string {
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSecs = Math.floor(diffMs / 1000);
  const diffMins = Math.floor(diffSecs / 60);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);
  const diffWeeks = Math.floor(diffDays / 7);
  const diffMonths = Math.floor(diffDays / 30);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffWeeks < 4) return `${diffWeeks}w ago`;
  return `${diffMonths}mo ago`;
}

/**
 * Create a horizontal rule
 */
export function horizontalRule(width: number, char: string = box.horizontal): string {
  return char.repeat(width);
}

/**
 * Create a boxed title
 */
export function boxedTitle(title: string, width: number): string[] {
  const innerWidth = width - 2;
  const padding = Math.floor((innerWidth - title.length) / 2);
  const paddedTitle = " ".repeat(padding) + title + " ".repeat(innerWidth - padding - title.length);

  return [
    box.topLeft + box.horizontal.repeat(innerWidth) + box.topRight,
    box.vertical + paddedTitle + box.vertical,
    box.bottomLeft + box.horizontal.repeat(innerWidth) + box.bottomRight,
  ];
}

/**
 * Pad string to specified length
 */
export function padEnd(str: string, length: number): string {
  if (str.length >= length) return str;
  return str + " ".repeat(length - str.length);
}

export function padStart(str: string, length: number): string {
  if (str.length >= length) return str;
  return " ".repeat(length - str.length) + str;
}

/**
 * Center string within specified width
 */
export function center(str: string, width: number): string {
  if (str.length >= width) return str;
  const leftPad = Math.floor((width - str.length) / 2);
  const rightPad = width - str.length - leftPad;
  return " ".repeat(leftPad) + str + " ".repeat(rightPad);
}

/**
 * Strip ANSI codes for length calculation
 */
export function stripAnsi(str: string): string {
  return str.replace(/\x1b\[[0-9;]*m/g, "");
}

/**
 * Get visible length of string (excluding ANSI codes)
 */
export function visibleLength(str: string): number {
  return stripAnsi(str).length;
}

/**
 * Format a key hint for the UI
 */
export function formatKeyHint(key: string, action: string): string {
  return `${colors.accent}[${key}]${colors.reset} ${colors.muted}${action}${colors.reset}`;
}

/**
 * Create a help bar with key hints
 */
export function createHelpBar(hints: Array<{ key: string; action: string }>): string {
  return hints.map((h) => formatKeyHint(h.key, h.action)).join("  ");
}
