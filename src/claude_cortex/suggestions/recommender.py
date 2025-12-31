"""Learning recommender for cross-project knowledge transfer."""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from ..ledger import Ledger, Learning


@dataclass
class ProjectAnalysis:
    """Analysis of a project's type and characteristics."""

    project_type: Optional[str] = None
    tech_stack: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    project_path: Optional[Path] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "project_type": self.project_type,
            "tech_stack": self.tech_stack,
            "keywords": self.keywords,
            "project_path": str(self.project_path) if self.project_path else None,
        }


@dataclass
class Suggestion:
    """A suggested learning from the global ledger."""

    learning: Learning
    relevance_score: float
    match_reasons: list[str] = field(default_factory=list)

    def format_summary(self, max_length: int = 150) -> str:
        """Format a summary of the suggestion for display."""
        content = self.learning.content
        if len(content) > max_length:
            content = content[:max_length - 3] + "..."
        return content


class LearningRecommender:
    """Recommends relevant learnings from global ledger for a project.

    Analyzes the current project to detect:
    - Project type (Python, Node.js, Rust, Go, etc.)
    - Tech stack (frameworks, libraries, tools)
    - Keywords from project files

    Then finds matching learnings from the global ledger.
    """

    # Common tech stack patterns to detect
    TECH_PATTERNS = {
        # Python
        "fastapi": ["fastapi", "starlette"],
        "django": ["django"],
        "flask": ["flask"],
        "pytest": ["pytest"],
        "pydantic": ["pydantic"],
        "sqlalchemy": ["sqlalchemy"],
        "asyncio": ["asyncio", "async", "await"],
        "celery": ["celery"],
        "redis": ["redis"],
        # Node.js
        "react": ["react", "jsx", "tsx"],
        "vue": ["vue"],
        "express": ["express"],
        "next": ["next", "nextjs"],
        "typescript": ["typescript", "ts"],
        "jest": ["jest"],
        "prisma": ["prisma"],
        # General
        "docker": ["docker", "dockerfile"],
        "kubernetes": ["kubernetes", "k8s"],
        "graphql": ["graphql"],
        "rest": ["rest", "api"],
        "postgres": ["postgres", "postgresql"],
        "mongodb": ["mongodb", "mongo"],
        "aws": ["aws", "amazon"],
        "gcp": ["gcp", "google cloud"],
        "azure": ["azure"],
        "ci/cd": ["ci", "cd", "github actions", "gitlab ci"],
        "testing": ["test", "spec", "mock"],
        "auth": ["auth", "jwt", "oauth", "authentication"],
    }

    def __init__(self, global_ledger: Ledger):
        """Initialize the recommender.

        Args:
            global_ledger: The global ledger to get suggestions from
        """
        self.global_ledger = global_ledger

    def analyze_project(self, project_path: Path) -> ProjectAnalysis:
        """Analyze a project to determine its type and characteristics.

        Args:
            project_path: Path to the project directory

        Returns:
            ProjectAnalysis with detected characteristics
        """
        analysis = ProjectAnalysis(project_path=project_path)

        # Detect project type
        analysis.project_type = self._detect_project_type(project_path)

        # Detect tech stack
        analysis.tech_stack = self._detect_tech_stack(project_path)

        # Extract keywords
        analysis.keywords = self._extract_keywords(project_path)

        return analysis

    def _detect_project_type(self, project_path: Path) -> Optional[str]:
        """Detect the primary project type."""
        # Check for Python
        if (project_path / "pyproject.toml").exists():
            return "python"
        if (project_path / "setup.py").exists():
            return "python"
        if (project_path / "requirements.txt").exists():
            return "python"

        # Check for Node.js
        if (project_path / "package.json").exists():
            return "node"

        # Check for Rust
        if (project_path / "Cargo.toml").exists():
            return "rust"

        # Check for Go
        if (project_path / "go.mod").exists():
            return "go"

        # Check for Java/Kotlin
        if (project_path / "pom.xml").exists():
            return "java"
        if (project_path / "build.gradle").exists():
            return "java"
        if (project_path / "build.gradle.kts").exists():
            return "kotlin"

        # Check for Ruby
        if (project_path / "Gemfile").exists():
            return "ruby"

        # Check for PHP
        if (project_path / "composer.json").exists():
            return "php"

        return None

    def _detect_tech_stack(self, project_path: Path) -> list[str]:
        """Detect technologies used in the project."""
        tech_stack = set()

        # Read pyproject.toml for Python
        pyproject = project_path / "pyproject.toml"
        if pyproject.exists():
            try:
                content = pyproject.read_text()
                content_lower = content.lower()
                for tech, patterns in self.TECH_PATTERNS.items():
                    for pattern in patterns:
                        if pattern in content_lower:
                            tech_stack.add(tech)
                            break
            except Exception:
                pass

        # Read package.json for Node.js
        package_json = project_path / "package.json"
        if package_json.exists():
            try:
                content = package_json.read_text()
                data = json.loads(content)
                deps = set()
                deps.update(data.get("dependencies", {}).keys())
                deps.update(data.get("devDependencies", {}).keys())

                for tech, patterns in self.TECH_PATTERNS.items():
                    for pattern in patterns:
                        if any(pattern in dep.lower() for dep in deps):
                            tech_stack.add(tech)
                            break
            except Exception:
                pass

        # Read Cargo.toml for Rust
        cargo = project_path / "Cargo.toml"
        if cargo.exists():
            try:
                content = cargo.read_text()
                content_lower = content.lower()
                for tech, patterns in self.TECH_PATTERNS.items():
                    for pattern in patterns:
                        if pattern in content_lower:
                            tech_stack.add(tech)
                            break
            except Exception:
                pass

        # Check for Docker
        if (project_path / "Dockerfile").exists() or (project_path / "docker-compose.yml").exists():
            tech_stack.add("docker")

        # Check for CI/CD
        if (project_path / ".github" / "workflows").exists():
            tech_stack.add("ci/cd")
        if (project_path / ".gitlab-ci.yml").exists():
            tech_stack.add("ci/cd")

        return sorted(tech_stack)

    def _extract_keywords(self, project_path: Path) -> list[str]:
        """Extract keywords from project files."""
        keywords = set()

        # Read README for keywords
        for readme_name in ["README.md", "README.rst", "README.txt", "README"]:
            readme = project_path / readme_name
            if readme.exists():
                try:
                    content = readme.read_text()
                    # Extract words that look like technical terms
                    words = re.findall(r'\b[A-Za-z][a-z]{2,}(?:[A-Z][a-z]+)*\b', content)
                    for word in words:
                        word_lower = word.lower()
                        # Skip common words
                        if word_lower not in {"the", "and", "for", "with", "this", "that", "from", "are", "was", "were", "been"}:
                            if len(word_lower) > 3:
                                keywords.add(word_lower)
                except Exception:
                    pass
                break

        # Read CLAUDE.md for domain-specific terms
        claude_md = project_path / "CLAUDE.md"
        if claude_md.exists():
            try:
                content = claude_md.read_text()
                words = re.findall(r'\b[A-Za-z][a-z]{2,}(?:[A-Z][a-z]+)*\b', content)
                for word in words:
                    word_lower = word.lower()
                    if len(word_lower) > 3:
                        keywords.add(word_lower)
            except Exception:
                pass

        # Limit to most relevant keywords (top 20)
        return sorted(keywords)[:20]

    def get_suggestions(
        self,
        project_path: Path,
        limit: int = 10,
        min_confidence: float = 0.5,
    ) -> list[Suggestion]:
        """Get suggested learnings for a project.

        Args:
            project_path: Path to the project directory
            limit: Maximum number of suggestions
            min_confidence: Minimum confidence threshold

        Returns:
            List of Suggestions sorted by relevance
        """
        analysis = self.analyze_project(project_path)
        return self.get_suggestions_for_analysis(analysis, limit, min_confidence)

    def get_suggestions_for_analysis(
        self,
        analysis: ProjectAnalysis,
        limit: int = 10,
        min_confidence: float = 0.5,
    ) -> list[Suggestion]:
        """Get suggested learnings based on project analysis.

        Args:
            analysis: Pre-computed project analysis
            limit: Maximum number of suggestions
            min_confidence: Minimum confidence threshold

        Returns:
            List of Suggestions sorted by relevance
        """
        # Get related learnings from global ledger
        related = self.global_ledger.get_related_learnings(
            project_type=analysis.project_type,
            keywords=analysis.keywords,
            tech_stack=analysis.tech_stack,
            min_confidence=min_confidence,
            limit=limit * 2,  # Get more to filter and score
        )

        suggestions = []
        for learning in related:
            score, reasons = self._score_learning(learning, analysis)
            if score > 0:
                suggestions.append(Suggestion(
                    learning=learning,
                    relevance_score=score,
                    match_reasons=reasons,
                ))

        # Sort by relevance score
        suggestions.sort(key=lambda s: s.relevance_score, reverse=True)

        return suggestions[:limit]

    def _score_learning(
        self,
        learning: Learning,
        analysis: ProjectAnalysis,
    ) -> tuple[float, list[str]]:
        """Score a learning's relevance to the project analysis.

        Returns:
            Tuple of (score, list of match reasons)
        """
        score = 0.0
        reasons = []

        # Base score from confidence
        score += learning.confidence * 0.3
        reasons.append(f"Confidence: {learning.confidence*100:.0f}%")

        # Project type match
        if analysis.project_type and learning.project_context:
            if learning.project_context.project_type:
                if learning.project_context.project_type.lower() == analysis.project_type.lower():
                    score += 0.25
                    reasons.append(f"Same project type: {analysis.project_type}")

        # Tech stack overlap
        if analysis.tech_stack and learning.project_context:
            ctx_stack = [t.lower() for t in learning.project_context.tech_stack]
            overlaps = set(t.lower() for t in analysis.tech_stack) & set(ctx_stack)
            if overlaps:
                score += min(0.25, len(overlaps) * 0.1)
                reasons.append(f"Tech stack: {', '.join(sorted(overlaps))}")

        # Keyword matching in content
        content_lower = learning.content.lower()
        matched_keywords = [k for k in analysis.keywords if k in content_lower]
        if matched_keywords:
            score += min(0.2, len(matched_keywords) * 0.05)
            reasons.append(f"Keywords: {', '.join(matched_keywords[:5])}")

        return score, reasons

    def get_top_suggestions_summary(
        self,
        project_path: Path,
        limit: int = 3,
    ) -> str:
        """Get a formatted summary of top suggestions for session context.

        Args:
            project_path: Path to the project directory
            limit: Number of suggestions to include

        Returns:
            Formatted string for session context injection
        """
        suggestions = self.get_suggestions(project_path, limit=limit)

        if not suggestions:
            return ""

        lines = ["## Suggested from Global Knowledge"]

        for i, suggestion in enumerate(suggestions, 1):
            summary = suggestion.format_summary(max_length=120)
            category = suggestion.learning.category.value
            confidence = int(suggestion.learning.confidence * 100)
            reasons = ", ".join(suggestion.match_reasons[:2])

            lines.append(f"{i}. [{category}] ({confidence}%): {summary}")
            lines.append(f"   Matched: {reasons}")

        return "\n".join(lines)
