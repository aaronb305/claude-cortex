import React, { useState, useEffect, useCallback } from "react";
import { Box, Text, useInput, useApp } from "ink";
import Spinner from "ink-spinner";
import { LearningList } from "./LearningList.js";
import { LearningDetail } from "./LearningDetail.js";
import { Search } from "./Search.js";
import {
  listLearnings,
  getStats,
  type Learning,
  type SearchResult,
} from "../api.js";

type View = "list" | "detail" | "search";

interface DashboardProps {
  projectPath?: string;
  initialView?: View;
}

// Box drawing characters
const BOX = {
  topLeft: "\u2554",
  topRight: "\u2557",
  bottomLeft: "\u255a",
  bottomRight: "\u255d",
  horizontal: "\u2550",
  vertical: "\u2551",
};

/**
 * Stats bar showing overview statistics
 */
function StatsBar({
  stats,
}: {
  stats: {
    totalLearnings: number;
    byCategory: Record<string, number>;
    avgConfidence: number;
    pendingOutcomes: number;
  };
}) {
  return (
    <Box flexDirection="row" justifyContent="space-between" marginBottom={1}>
      <Box>
        <Text color="cyan" bold>
          {"\u2605"} Total: {stats.totalLearnings}
        </Text>
      </Box>
      <Box>
        <Text color="cyan">{"\u2605"} </Text>
        <Text color="gray">D:{stats.byCategory.discovery || 0}</Text>
        <Text color="gray"> | </Text>
        <Text color="yellow">D:{stats.byCategory.decision || 0}</Text>
        <Text color="gray"> | </Text>
        <Text color="red">E:{stats.byCategory.error || 0}</Text>
        <Text color="gray"> | </Text>
        <Text color="magenta">P:{stats.byCategory.pattern || 0}</Text>
      </Box>
      <Box>
        <Text color="gray">Avg Confidence: </Text>
        <Text color={stats.avgConfidence >= 0.7 ? "green" : "yellow"}>
          {Math.round(stats.avgConfidence * 100)}%
        </Text>
      </Box>
      {stats.pendingOutcomes > 0 && (
        <Box>
          <Text color="yellow">
            {"\u26A0"} {stats.pendingOutcomes} pending outcomes
          </Text>
        </Box>
      )}
    </Box>
  );
}

/**
 * Header with title and navigation hints
 */
function Header({ currentView }: { currentView: View }) {
  return (
    <Box flexDirection="column" marginBottom={1}>
      <Box>
        <Text color="cyan" bold>
          {BOX.topLeft}
          {BOX.horizontal.repeat(3)}
        </Text>
        <Text color="white" bold>
          {" "}
          Claude Cortex Dashboard{" "}
        </Text>
        <Text color="cyan" bold>
          {BOX.horizontal.repeat(3)}
          {BOX.topRight}
        </Text>
      </Box>
      <Box>
        <Text color="gray">
          View:{" "}
          <Text color={currentView === "list" ? "cyan" : "gray"} bold={currentView === "list"}>
            [L]ist
          </Text>{" "}
          <Text color={currentView === "search" ? "cyan" : "gray"} bold={currentView === "search"}>
            [/]Search
          </Text>{" "}
          <Text color={currentView === "detail" ? "cyan" : "gray"} bold={currentView === "detail"}>
            [Enter]Detail
          </Text>
        </Text>
      </Box>
    </Box>
  );
}

/**
 * Help bar at the bottom
 */
function HelpBar({ view }: { view: View }) {
  const hints: Record<View, string> = {
    list: "[j/k] navigate | [/] search | [Enter] details | [r] refresh | [q] quit",
    detail: "[Esc] back to list | [o] record outcome | [q] quit",
    search: "[Tab] toggle focus | [j/k] navigate | [Enter] select | [Esc] close",
  };

  return (
    <Box marginTop={1} borderStyle="single" borderColor="gray" paddingX={1}>
      <Text color="gray">{hints[view]}</Text>
    </Box>
  );
}

/**
 * Main dashboard component
 */
export function Dashboard({ projectPath, initialView = "list" }: DashboardProps) {
  const { exit } = useApp();

  // State
  const [view, setView] = useState<View>(initialView);
  const [learnings, setLearnings] = useState<Learning[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [selectedLearning, setSelectedLearning] = useState<Learning | null>(null);
  const [stats, setStats] = useState<{
    totalLearnings: number;
    byCategory: Record<string, number>;
    avgConfidence: number;
    pendingOutcomes: number;
  }>({
    totalLearnings: 0,
    byCategory: { discovery: 0, decision: 0, error: 0, pattern: 0 },
    avgConfidence: 0,
    pendingOutcomes: 0,
  });
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load data
  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [learningsData, statsData] = await Promise.all([
        listLearnings({ showDecay: true, projectPath }),
        getStats({ projectPath }),
      ]);
      setLearnings(learningsData);
      setStats(statsData);

      // Update selected learning based on current state
      setSelectedLearning((current) => {
        if (current) {
          const updated = learningsData.find((l) => l.id === current.id);
          return updated || current;
        }
        return learningsData[0] || null;
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load data");
    } finally {
      setIsLoading(false);
    }
  }, [projectPath]);

  // Initial load
  useEffect(() => {
    loadData();
  }, [loadData]);

  // Handle keyboard input
  useInput((input, key) => {
    // Global shortcuts
    if (input === "q" && view !== "search") {
      exit();
      return;
    }

    if (input === "r" && view !== "search") {
      loadData();
      return;
    }

    // View-specific shortcuts
    switch (view) {
      case "list":
        if (input === "j" || key.downArrow) {
          const next = Math.min(selectedIndex + 1, learnings.length - 1);
          setSelectedIndex(next);
          setSelectedLearning(learnings[next] || null);
        } else if (input === "k" || key.upArrow) {
          const next = Math.max(selectedIndex - 1, 0);
          setSelectedIndex(next);
          setSelectedLearning(learnings[next] || null);
        } else if (input === "/" || input === "s") {
          setView("search");
        } else if (key.return && selectedLearning) {
          setView("detail");
        } else if (input === "g") {
          setSelectedIndex(0);
          setSelectedLearning(learnings[0] || null);
        } else if (input === "G") {
          const lastIndex = learnings.length - 1;
          setSelectedIndex(lastIndex);
          setSelectedLearning(learnings[lastIndex] || null);
        }
        break;

      case "detail":
        if (key.escape || input === "l") {
          setView("list");
        } else if (input === "/") {
          setView("search");
        }
        break;

      case "search":
        // Search handles its own input
        break;
    }
  });

  // Handle search selection
  const handleSearchSelect = (result: Learning | SearchResult) => {
    const fullLearning = learnings.find((l) => l.id === result.id);
    if (fullLearning) {
      setSelectedLearning(fullLearning);
      const idx = learnings.indexOf(fullLearning);
      if (idx !== -1) setSelectedIndex(idx);
    } else {
      // Treat search result as learning
      setSelectedLearning(result as Learning);
    }
    setView("detail");
  };

  // Loading state
  if (isLoading && learnings.length === 0) {
    return (
      <Box flexDirection="column" padding={1}>
        <Header currentView={view} />
        <Box>
          <Text color="cyan">
            <Spinner type="dots" />
          </Text>
          <Text color="gray"> Loading learnings...</Text>
        </Box>
      </Box>
    );
  }

  // Error state
  if (error && learnings.length === 0) {
    return (
      <Box flexDirection="column" padding={1}>
        <Header currentView={view} />
        <Box>
          <Text color="red">{"\u2717"} Error: {error}</Text>
        </Box>
        <Box marginTop={1}>
          <Text color="gray">Press [r] to retry or [q] to quit</Text>
        </Box>
      </Box>
    );
  }

  return (
    <Box flexDirection="column" padding={1}>
      <Header currentView={view} />
      <StatsBar stats={stats} />

      {isLoading && (
        <Box marginBottom={1}>
          <Text color="cyan">
            <Spinner type="dots" />
          </Text>
          <Text color="gray"> Refreshing...</Text>
        </Box>
      )}

      {view === "list" && (
        <Box flexDirection="row">
          {/* Main list */}
          <Box flexDirection="column" width="60%">
            <LearningList
              learnings={learnings}
              selectedIndex={selectedIndex}
              height={15}
            />
          </Box>

          {/* Detail preview */}
          <Box flexDirection="column" width="40%" marginLeft={1}>
            <LearningDetail learning={selectedLearning} />
          </Box>
        </Box>
      )}

      {view === "detail" && selectedLearning && (
        <LearningDetail learning={selectedLearning} />
      )}

      {view === "search" && (
        <Search
          onSelect={handleSearchSelect}
          onClose={() => setView("list")}
          projectPath={projectPath}
        />
      )}

      <HelpBar view={view} />
    </Box>
  );
}

export default Dashboard;
