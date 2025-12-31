import React from "react";
import { Box, Text } from "ink";
import type { Learning } from "../api.js";

interface LearningListProps {
  learnings: Learning[];
  selectedIndex: number;
  height?: number;
}

// Category colors
const categoryColors: Record<string, string> = {
  discovery: "cyan",
  decision: "yellow",
  error: "red",
  pattern: "magenta",
};

// Category icons
const categoryIcons: Record<string, string> = {
  discovery: "\u2605", // Star
  decision: "\u2713", // Check mark
  error: "\u2717", // X mark
  pattern: "\u2261", // Three horizontal lines
};

/**
 * Render a confidence bar using block characters
 */
function ConfidenceBar({
  confidence,
  width = 10,
}: {
  confidence: number;
  width?: number;
}) {
  const filled = Math.round(confidence * width);
  const empty = width - filled;

  let color: "green" | "yellow" | "red" = "green";
  if (confidence < 0.5) color = "red";
  else if (confidence < 0.8) color = "yellow";

  return (
    <Text>
      <Text color={color}>{"\u2588".repeat(filled)}</Text>
      <Text color="gray">{"\u2591".repeat(empty)}</Text>
      <Text color="gray"> {Math.round(confidence * 100)}%</Text>
    </Text>
  );
}

/**
 * Single learning item in the list
 */
function LearningItem({
  learning,
  isSelected,
  width = 80,
}: {
  learning: Learning;
  isSelected: boolean;
  width?: number;
}) {
  const category = learning.category || "discovery";
  const color = categoryColors[category] || "white";
  const icon = categoryIcons[category] || "\u2022";

  // Calculate content width (minus decorations)
  const contentWidth = width - 40; // Account for margins, confidence bar, etc.
  const truncatedContent =
    learning.content.length > contentWidth
      ? learning.content.slice(0, contentWidth - 3) + "..."
      : learning.content;

  return (
    <Box
      flexDirection="row"
      paddingX={1}
      borderStyle={isSelected ? "round" : undefined}
      borderColor={isSelected ? "cyan" : undefined}
    >
      {/* Category icon */}
      <Box width={3}>
        <Text color={color}>{icon}</Text>
      </Box>

      {/* Category tag */}
      <Box width={12}>
        <Text color={color} bold={isSelected}>
          {category.toUpperCase()}
        </Text>
      </Box>

      {/* Content */}
      <Box flexGrow={1} marginRight={1}>
        <Text color={isSelected ? "white" : "gray"} wrap="truncate">
          {truncatedContent.replace(/\n/g, " ")}
        </Text>
      </Box>

      {/* Confidence bar */}
      <Box width={20}>
        <ConfidenceBar
          confidence={learning.effective_confidence ?? learning.confidence}
          width={8}
        />
      </Box>
    </Box>
  );
}

/**
 * List of learnings with scrolling support
 */
export function LearningList({
  learnings,
  selectedIndex,
  height = 15,
}: LearningListProps) {
  // Calculate scroll window
  const windowSize = height - 2; // Account for borders
  let startIndex = 0;

  if (selectedIndex >= windowSize) {
    startIndex = selectedIndex - windowSize + 1;
  }

  const visibleLearnings = learnings.slice(startIndex, startIndex + windowSize);

  if (learnings.length === 0) {
    return (
      <Box
        flexDirection="column"
        borderStyle="round"
        borderColor="gray"
        paddingX={2}
        paddingY={1}
      >
        <Text color="gray" italic>
          No learnings found. Use Claude to discover and capture insights!
        </Text>
      </Box>
    );
  }

  return (
    <Box flexDirection="column">
      {/* Header */}
      <Box marginBottom={1}>
        <Text color="cyan" bold>
          {"\u250c"} Learnings ({learnings.length} total)
        </Text>
      </Box>

      {/* List items */}
      <Box flexDirection="column">
        {visibleLearnings.map((learning, index) => (
          <LearningItem
            key={learning.id}
            learning={learning}
            isSelected={startIndex + index === selectedIndex}
          />
        ))}
      </Box>

      {/* Scroll indicator */}
      {learnings.length > windowSize && (
        <Box marginTop={1}>
          <Text color="gray">
            {"\u2191\u2193"} {selectedIndex + 1}/{learnings.length}
            {startIndex > 0 && " (scroll up for more)"}
            {startIndex + windowSize < learnings.length &&
              " (scroll down for more)"}
          </Text>
        </Box>
      )}
    </Box>
  );
}

export default LearningList;
