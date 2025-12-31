import React, { useState, useEffect } from "react";
import { Box, Text, useInput } from "ink";
import TextInput from "ink-text-input";
import type { Learning, SearchResult } from "../api.js";
import { searchLearnings } from "../api.js";

interface SearchProps {
  onSelect: (learning: Learning | SearchResult) => void;
  onClose: () => void;
  projectPath?: string;
}

// Category colors
const categoryColors: Record<string, string> = {
  discovery: "cyan",
  decision: "yellow",
  error: "red",
  pattern: "magenta",
};

/**
 * Search result item
 */
function SearchResultItem({
  result,
  isSelected,
}: {
  result: SearchResult;
  isSelected: boolean;
}) {
  const color = categoryColors[result.category] || "white";
  const truncatedContent =
    result.content.length > 60
      ? result.content.slice(0, 57) + "..."
      : result.content;

  return (
    <Box
      paddingX={1}
      borderStyle={isSelected ? "round" : undefined}
      borderColor={isSelected ? "cyan" : undefined}
    >
      <Box width={12}>
        <Text color={color}>{result.category.toUpperCase()}</Text>
      </Box>
      <Box flexGrow={1}>
        <Text color={isSelected ? "white" : "gray"} wrap="truncate">
          {truncatedContent.replace(/\n/g, " ")}
        </Text>
      </Box>
      <Box width={8}>
        <Text color="gray">{Math.round(result.confidence * 100)}%</Text>
      </Box>
      {result.score !== undefined && (
        <Box width={10}>
          <Text color="yellow">score: {result.score.toFixed(2)}</Text>
        </Box>
      )}
    </Box>
  );
}

/**
 * Search view with real-time filtering
 */
export function Search({ onSelect, onClose, projectPath }: SearchProps) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isInputFocused, setIsInputFocused] = useState(true);

  // Debounced search
  useEffect(() => {
    if (query.length < 2) {
      setResults([]);
      return;
    }

    const timer = setTimeout(async () => {
      setIsLoading(true);
      setError(null);
      try {
        const searchResults = await searchLearnings(query, {
          limit: 20,
          projectPath,
        });
        setResults(searchResults);
        setSelectedIndex(0);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Search failed");
        setResults([]);
      } finally {
        setIsLoading(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [query, projectPath]);

  // Handle keyboard navigation
  useInput(
    (input, key) => {
      if (key.escape) {
        onClose();
        return;
      }

      if (key.return && results.length > 0) {
        onSelect(results[selectedIndex]);
        return;
      }

      // Vim-style navigation when not focused on input
      if (!isInputFocused) {
        if (input === "j" || key.downArrow) {
          setSelectedIndex((prev) => Math.min(prev + 1, results.length - 1));
        } else if (input === "k" || key.upArrow) {
          setSelectedIndex((prev) => Math.max(prev - 1, 0));
        } else if (input === "i") {
          setIsInputFocused(true);
        } else if (input === "q") {
          onClose();
        }
      }

      // Tab toggles focus
      if (key.tab) {
        setIsInputFocused((prev) => !prev);
      }
    },
    { isActive: true }
  );

  return (
    <Box flexDirection="column" paddingX={1}>
      {/* Search header */}
      <Box marginBottom={1}>
        <Text color="cyan" bold>
          {"\u2605"} Search Learnings
        </Text>
      </Box>

      {/* Search input */}
      <Box
        borderStyle="round"
        borderColor={isInputFocused ? "cyan" : "gray"}
        paddingX={1}
        marginBottom={1}
      >
        <Text color="cyan">{"\u2315"} </Text>
        <TextInput
          value={query}
          onChange={setQuery}
          placeholder="Type to search..."
          focus={isInputFocused}
        />
        {isLoading && (
          <Text color="yellow"> {"\u231B"}</Text>
        )}
      </Box>

      {/* Error display */}
      {error && (
        <Box marginBottom={1}>
          <Text color="red">{"\u2717"} {error}</Text>
        </Box>
      )}

      {/* Results list */}
      <Box flexDirection="column" borderStyle="round" borderColor="gray" padding={1}>
        {query.length < 2 ? (
          <Text color="gray" italic>
            Enter at least 2 characters to search
          </Text>
        ) : results.length === 0 && !isLoading ? (
          <Text color="gray" italic>
            No results found for "{query}"
          </Text>
        ) : (
          results.slice(0, 10).map((result, index) => (
            <SearchResultItem
              key={result.id}
              result={result}
              isSelected={index === selectedIndex}
            />
          ))
        )}

        {results.length > 10 && (
          <Box marginTop={1}>
            <Text color="gray">... and {results.length - 10} more results</Text>
          </Box>
        )}
      </Box>

      {/* Help text */}
      <Box marginTop={1}>
        <Text color="gray">
          <Text color="cyan">[Tab]</Text> toggle focus{" "}
          <Text color="cyan">[j/k]</Text> navigate{" "}
          <Text color="cyan">[Enter]</Text> select{" "}
          <Text color="cyan">[Esc/q]</Text> close
        </Text>
      </Box>
    </Box>
  );
}

export default Search;
