/**
 * API module for interacting with the Claude Cortex Python CLI
 * Provides typed interfaces for ledger data and CLI command execution
 */

import { $ } from "bun";

// Types for learning data
export interface Learning {
  id: string;
  category: "discovery" | "decision" | "error" | "pattern";
  content: string;
  confidence: number;
  effective_confidence?: number;
  timestamp: string;
  project?: string;
  tags?: string[];
  derived_from?: string;
  promoted_to?: string;
  outcome_count?: number;
  last_touched?: string;
}

export interface LearningListResponse {
  learnings: Learning[];
  total: number;
}

export interface SearchResult {
  id: string;
  category: string;
  content: string;
  confidence: number;
  score?: number;
}

export interface HandoffData {
  session_id: string;
  timestamp: string;
  completed_tasks: string[];
  pending_tasks: string[];
  context?: string;
  notes?: string;
}

export interface SyncStatus {
  status: "IN_SYNC" | "LOCAL_AHEAD" | "REMOTE_AHEAD" | "DIVERGED";
  local_blocks: number;
  merkle_root?: string;
}

// CLI execution helper
async function runCclaude(
  args: string[],
  options: { projectPath?: string } = {}
): Promise<string> {
  const projectArgs = options.projectPath ? ["-p", options.projectPath] : [];
  const cmd = ["uv", "run", "cclaude", ...args, ...projectArgs];

  try {
    const result = await $`${cmd}`.quiet().text();
    return result.trim();
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`CLI command failed: ${error.message}`);
    }
    throw error;
  }
}

// Parse JSON safely
function parseJSON<T>(text: string): T {
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(`Failed to parse JSON: ${text.slice(0, 100)}...`);
  }
}

/**
 * List learnings from the ledger
 */
export async function listLearnings(options: {
  minConfidence?: number;
  category?: string;
  limit?: number;
  showDecay?: boolean;
  projectPath?: string;
}): Promise<Learning[]> {
  const args = ["list", "--json"];

  if (options.minConfidence !== undefined) {
    args.push("--min-confidence", options.minConfidence.toString());
  }
  if (options.category) {
    args.push("--category", options.category);
  }
  if (options.limit) {
    args.push("--limit", options.limit.toString());
  }
  if (options.showDecay) {
    args.push("--show-decay");
  }

  try {
    const output = await runCclaude(args, { projectPath: options.projectPath });
    if (!output) return [];
    const data = parseJSON<LearningListResponse | Learning[]>(output);
    return Array.isArray(data) ? data : data.learnings;
  } catch {
    // Fall back to parsing non-JSON output
    return [];
  }
}

/**
 * Get a single learning by ID
 */
export async function getLearning(
  id: string,
  options: { showDecay?: boolean; projectPath?: string } = {}
): Promise<Learning | null> {
  const args = ["show", id, "--json"];

  if (options.showDecay) {
    args.push("--show-decay");
  }

  try {
    const output = await runCclaude(args, { projectPath: options.projectPath });
    if (!output) return null;
    return parseJSON<Learning>(output);
  } catch {
    return null;
  }
}

/**
 * Search learnings
 */
export async function searchLearnings(
  query: string,
  options: { category?: string; limit?: number; projectPath?: string } = {}
): Promise<SearchResult[]> {
  const args = ["search", query, "--json"];

  if (options.category) {
    args.push("--category", options.category);
  }
  if (options.limit) {
    args.push("--limit", options.limit.toString());
  }

  try {
    const output = await runCclaude(args, { projectPath: options.projectPath });
    if (!output) return [];
    return parseJSON<SearchResult[]>(output);
  } catch {
    return [];
  }
}

/**
 * Record an outcome for a learning
 */
export async function recordOutcome(
  id: string,
  result: "success" | "partial" | "failure",
  comment?: string,
  options: { projectPath?: string } = {}
): Promise<boolean> {
  const args = ["outcome", id, "-r", result];

  if (comment) {
    args.push("-c", comment);
  }

  try {
    await runCclaude(args, { projectPath: options.projectPath });
    return true;
  } catch {
    return false;
  }
}

/**
 * Get pending outcomes
 */
export async function getPendingOutcomes(
  options: { projectPath?: string } = {}
): Promise<Learning[]> {
  try {
    const output = await runCclaude(["outcomes", "pending", "--json"], options);
    if (!output) return [];
    return parseJSON<Learning[]>(output);
  } catch {
    return [];
  }
}

/**
 * Get current handoff
 */
export async function getHandoff(
  options: { projectPath?: string } = {}
): Promise<HandoffData | null> {
  try {
    const output = await runCclaude(["handoff", "show", "--json"], options);
    if (!output) return null;
    return parseJSON<HandoffData>(output);
  } catch {
    return null;
  }
}

/**
 * Get sync status
 */
export async function getSyncStatus(
  options: { projectPath?: string } = {}
): Promise<SyncStatus | null> {
  try {
    const output = await runCclaude(["sync", "status", "--json"], options);
    if (!output) return null;
    return parseJSON<SyncStatus>(output);
  } catch {
    return null;
  }
}

/**
 * Verify ledger integrity
 */
export async function verifyLedger(
  options: { merkle?: boolean; signatures?: boolean; projectPath?: string } = {}
): Promise<{ valid: boolean; errors: string[] }> {
  const args = ["verify"];

  if (options.merkle) {
    args.push("--merkle");
  }
  if (options.signatures) {
    args.push("--signatures");
  }

  try {
    await runCclaude(args, { projectPath: options.projectPath });
    return { valid: true, errors: [] };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    return { valid: false, errors: [message] };
  }
}

/**
 * Get ledger statistics
 */
export async function getStats(
  options: { projectPath?: string } = {}
): Promise<{
  totalLearnings: number;
  byCategory: Record<string, number>;
  avgConfidence: number;
  pendingOutcomes: number;
}> {
  try {
    const learnings = await listLearnings({ ...options, showDecay: true });

    const byCategory: Record<string, number> = {
      discovery: 0,
      decision: 0,
      error: 0,
      pattern: 0,
    };

    let totalConfidence = 0;

    for (const learning of learnings) {
      byCategory[learning.category] = (byCategory[learning.category] || 0) + 1;
      totalConfidence += learning.effective_confidence ?? learning.confidence;
    }

    const pending = await getPendingOutcomes(options);

    return {
      totalLearnings: learnings.length,
      byCategory,
      avgConfidence: learnings.length > 0 ? totalConfidence / learnings.length : 0,
      pendingOutcomes: pending.length,
    };
  } catch {
    return {
      totalLearnings: 0,
      byCategory: { discovery: 0, decision: 0, error: 0, pattern: 0 },
      avgConfidence: 0,
      pendingOutcomes: 0,
    };
  }
}
