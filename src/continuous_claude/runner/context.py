"""Context builder for constructing prompts from ledger knowledge."""

from pathlib import Path
from typing import Optional

from ..ledger import Ledger, LearningCategory


class ContextBuilder:
    """Builds context for Claude from ledger knowledge."""

    def __init__(
        self,
        project_ledger: Optional[Ledger] = None,
        global_ledger: Optional[Ledger] = None,
    ):
        """Initialize the context builder.

        Args:
            project_ledger: Project-specific ledger
            global_ledger: Global ledger for cross-project knowledge
        """
        self.project_ledger = project_ledger
        self.global_ledger = global_ledger

    def detect_project_type(self, project_path: Path) -> dict:
        """Detect project type and relevant tooling.

        Args:
            project_path: Path to the project root

        Returns:
            Dict with project type info and commands
        """
        result = {
            "type": "unknown",
            "package_manager": None,
            "commands": {},
        }

        # Check for Python project
        pyproject = project_path / "pyproject.toml"
        if pyproject.exists():
            result["type"] = "python"
            result["package_manager"] = "uv"
            result["commands"] = {
                "install": "uv sync",
                "run": "uv run python",
                "test": "uv run pytest",
                "add_dep": "uv add",
            }
            return result

        # Check for Node.js project
        package_json = project_path / "package.json"
        if package_json.exists():
            # Check for bun.lockb (bun preferred)
            if (project_path / "bun.lockb").exists():
                result["type"] = "node"
                result["package_manager"] = "bun"
                result["commands"] = {
                    "install": "bun install",
                    "run": "bun run",
                    "test": "bun test",
                    "add_dep": "bun add",
                }
            else:
                result["type"] = "node"
                result["package_manager"] = "npm"
                result["commands"] = {
                    "install": "npm install",
                    "run": "npm run",
                    "test": "npm test",
                    "add_dep": "npm install",
                }
            return result

        return result

    def build_knowledge_context(
        self,
        min_confidence: float = 0.5,
        max_items: int = 20,
        categories: Optional[list[LearningCategory]] = None,
    ) -> str:
        """Build a context string from high-confidence learnings.

        Args:
            min_confidence: Minimum confidence to include
            max_items: Maximum number of learnings to include
            categories: Filter by specific categories

        Returns:
            Formatted context string for Claude
        """
        learnings = []

        # Gather from project ledger
        if self.project_ledger:
            for cat in categories or list(LearningCategory):
                project_learnings = self.project_ledger.get_learnings_by_confidence(
                    min_confidence=min_confidence,
                    category=cat,
                    limit=max_items,
                )
                learnings.extend(project_learnings)

        # Gather from global ledger
        if self.global_ledger:
            for cat in categories or list(LearningCategory):
                global_learnings = self.global_ledger.get_learnings_by_confidence(
                    min_confidence=min_confidence,
                    category=cat,
                    limit=max_items,
                )
                # Mark as global
                for l in global_learnings:
                    l["source"] = "global"
                learnings.extend(global_learnings)

        # Sort by confidence and limit
        learnings.sort(key=lambda x: x["confidence"], reverse=True)
        learnings = learnings[:max_items]

        if not learnings:
            return ""

        # Format context
        lines = ["# Prior Knowledge", ""]
        lines.append("The following insights have been learned from previous sessions:")
        lines.append("")

        for learning in learnings:
            confidence_pct = int(learning["confidence"] * 100)
            category = learning["category"]
            source = learning.get("source", "project")
            lines.append(f"- [{category}] (confidence: {confidence_pct}%, {source})")

            # Get actual content from blocks
            if self.project_ledger:
                for block in self.project_ledger.get_all_blocks():
                    for l in block.learnings:
                        if l.id == learning["id"]:
                            lines.append(f"  {l.content}")
                            if l.source:
                                lines.append(f"  Source: {l.source}")
                            break

            if self.global_ledger and learning.get("source") == "global":
                for block in self.global_ledger.get_all_blocks():
                    for l in block.learnings:
                        if l.id == learning["id"]:
                            lines.append(f"  {l.content}")
                            if l.source:
                                lines.append(f"  Source: {l.source}")
                            break

            lines.append("")

        return "\n".join(lines)

    def build_project_context(self, project_path: Path) -> str:
        """Build project-specific context including tooling info.

        Args:
            project_path: Path to the project root

        Returns:
            Formatted context string
        """
        project_info = self.detect_project_type(project_path)

        if project_info["type"] == "unknown":
            return ""

        lines = ["# Project Environment", ""]
        lines.append(f"Project type: {project_info['type']}")
        lines.append(f"Package manager: {project_info['package_manager']}")
        lines.append("")
        lines.append("## Commands")

        for name, cmd in project_info["commands"].items():
            lines.append(f"- {name}: `{cmd}`")

        lines.append("")
        return "\n".join(lines)

    def build_full_context(
        self,
        project_path: Path,
        user_prompt: str,
        min_confidence: float = 0.5,
    ) -> str:
        """Build the complete context for a Claude session.

        Args:
            project_path: Path to the project
            user_prompt: The user's original prompt
            min_confidence: Minimum confidence for learnings

        Returns:
            Complete context string
        """
        parts = []

        # Add project context
        project_ctx = self.build_project_context(project_path)
        if project_ctx:
            parts.append(project_ctx)

        # Add knowledge context
        knowledge_ctx = self.build_knowledge_context(min_confidence=min_confidence)
        if knowledge_ctx:
            parts.append(knowledge_ctx)

        # Add user prompt
        parts.append("# Task")
        parts.append("")
        parts.append(user_prompt)

        return "\n".join(parts)
