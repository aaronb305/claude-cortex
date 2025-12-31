import React from "react";
import { Box, Text } from "ink";
import type { Learning } from "../api.js";

interface LearningDetailProps {
  learning: Learning | null;
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
 * Confidence bar with detailed display
 */
function DetailedConfidenceBar({
  confidence,
  effectiveConfidence,
}: {
  confidence: number;
  effectiveConfidence?: number;
}) {
  const width = 20;
  const filled = Math.round((effectiveConfidence ?? confidence) * width);
  const empty = width - filled;

  let color: "green" | "yellow" | "red" = "green";
  const effectiveValue = effectiveConfidence ?? confidence;
  if (effectiveValue < 0.5) color = "red";
  else if (effectiveValue < 0.8) color = "yellow";

  const hasDecay = effectiveConfidence !== undefined && effectiveConfidence !== confidence;

  return (
    <Box flexDirection="column">
      <Box>
        <Text color={color}>{"\u2588".repeat(filled)}</Text>
        <Text color="gray">{"\u2591".repeat(empty)}</Text>
      </Box>
      <Box marginTop={0}>
        <Text color="gray">
          {hasDecay ? (
            <>
              <Text color={color}>{Math.round(effectiveValue * 100)}%</Text>
              <Text color="gray"> (stored: {Math.round(confidence * 100)}%)</Text>
            </>
          ) : (
            <Text color={color}>{Math.round(confidence * 100)}%</Text>
          )}
        </Text>
      </Box>
    </Box>
  );
}

/**
 * Format timestamp for display
 */
function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  return date.toLocaleString();
}

/**
 * Wrap text to specified width
 */
function wrapText(text: string, width: number): string[] {
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
 * Detailed view of a single learning
 */
export function LearningDetail({ learning }: LearningDetailProps) {
  if (!learning) {
    return (
      <Box
        flexDirection="column"
        borderStyle="round"
        borderColor="gray"
        paddingX={2}
        paddingY={1}
      >
        <Text color="gray" italic>
          Select a learning to view details
        </Text>
      </Box>
    );
  }

  const category = learning.category || "discovery";
  const color = categoryColors[category] || "white";
  const icon = categoryIcons[category] || "\u2022";

  // Wrap content for display
  const contentLines = wrapText(learning.content, 70);

  return (
    <Box flexDirection="column" paddingX={1}>
      {/* Header with category */}
      <Box
        flexDirection="row"
        borderStyle="single"
        borderColor={color}
        paddingX={2}
        paddingY={0}
        marginBottom={1}
      >
        <Text color={color} bold>
          {icon} {category.toUpperCase()}
        </Text>
        <Text color="gray"> | </Text>
        <Text color="gray">ID: {learning.id.slice(0, 12)}...</Text>
      </Box>

      {/* Content */}
      <Box
        flexDirection="column"
        borderStyle="round"
        borderColor="gray"
        paddingX={2}
        paddingY={1}
        marginBottom={1}
      >
        <Box marginBottom={1}>
          <Text color="cyan" bold>
            Content
          </Text>
        </Box>
        {contentLines.map((line, i) => (
          <Text key={i} color="white">
            {line}
          </Text>
        ))}
      </Box>

      {/* Metadata grid */}
      <Box flexDirection="row" marginBottom={1}>
        {/* Left column */}
        <Box flexDirection="column" width="50%">
          <Box marginBottom={1}>
            <Text color="cyan" bold>
              Confidence
            </Text>
          </Box>
          <DetailedConfidenceBar
            confidence={learning.confidence}
            effectiveConfidence={learning.effective_confidence}
          />
        </Box>

        {/* Right column */}
        <Box flexDirection="column" width="50%">
          <Box marginBottom={1}>
            <Text color="cyan" bold>
              Timestamp
            </Text>
          </Box>
          <Text color="gray">{formatTimestamp(learning.timestamp)}</Text>

          {learning.last_touched && (
            <Box marginTop={1}>
              <Text color="gray" dimColor>
                Last used: {formatTimestamp(learning.last_touched)}
              </Text>
            </Box>
          )}
        </Box>
      </Box>

      {/* Additional metadata */}
      <Box flexDirection="column" marginTop={1}>
        {learning.project && (
          <Box>
            <Text color="cyan">Project: </Text>
            <Text color="gray">{learning.project}</Text>
          </Box>
        )}

        {learning.tags && learning.tags.length > 0 && (
          <Box>
            <Text color="cyan">Tags: </Text>
            <Text color="gray">{learning.tags.join(", ")}</Text>
          </Box>
        )}

        {learning.derived_from && (
          <Box>
            <Text color="yellow">Derived from: </Text>
            <Text color="gray">{learning.derived_from}</Text>
          </Box>
        )}

        {learning.promoted_to && (
          <Box>
            <Text color="green">Promoted to: </Text>
            <Text color="gray">{learning.promoted_to}</Text>
          </Box>
        )}

        {learning.outcome_count !== undefined && learning.outcome_count > 0 && (
          <Box>
            <Text color="cyan">Outcomes recorded: </Text>
            <Text color="white">{learning.outcome_count}</Text>
          </Box>
        )}
      </Box>
    </Box>
  );
}

export default LearningDetail;
