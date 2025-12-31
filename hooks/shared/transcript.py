#!/usr/bin/env python3
"""
Transcript reading and parsing utilities.
"""

import json


def read_transcript(transcript_path: str) -> list[dict]:
    """Read the session transcript (JSONL format).

    Args:
        transcript_path: Path to the transcript file.

    Returns:
        List of event dictionaries parsed from the transcript.
    """
    events = []
    try:
        with open(transcript_path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        pass
    return events


def extract_assistant_messages(events: list[dict]) -> str:
    """Extract all assistant messages from transcript events.

    Handles multiple event formats that may appear in transcripts.

    Args:
        events: List of event dictionaries from the transcript.

    Returns:
        Concatenated text from all assistant messages.
    """
    messages = []

    for event in events:
        # Handle standard event format
        if event.get("type") == "assistant":
            content = event.get("message", {}).get("content", [])
            for block in content:
                if block.get("type") == "text":
                    messages.append(block.get("text", ""))

        # Handle alternative format
        elif "content" in event and isinstance(event["content"], list):
            for block in event["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    messages.append(block.get("text", ""))

    return "\n\n".join(messages)


__all__ = ["read_transcript", "extract_assistant_messages"]
