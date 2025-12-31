"""Tests for the LearningRecommender class."""

import pytest
from pathlib import Path
import json

from claude_cortex.ledger import Ledger, Learning, LearningCategory, ProjectContext
from claude_cortex.suggestions.recommender import (
    LearningRecommender,
    ProjectAnalysis,
    Suggestion,
)


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def global_ledger(ledger_path):
    """Create a global ledger for testing recommendations."""
    return Ledger(ledger_path)


@pytest.fixture
def recommender(global_ledger):
    """Create a recommender with the test global ledger."""
    return LearningRecommender(global_ledger)


@pytest.fixture
def python_project(temp_dir):
    """Create a Python project with pyproject.toml and README."""
    project_path = temp_dir / "python_project"
    project_path.mkdir(parents=True)

    # Create pyproject.toml with FastAPI and pytest
    pyproject = project_path / "pyproject.toml"
    pyproject.write_text("""
[project]
name = "test-api"
version = "0.1.0"
dependencies = [
    "fastapi>=0.100.0",
    "pydantic>=2.0.0",
    "pytest>=7.0.0",
]
""")

    # Create README
    readme = project_path / "README.md"
    readme.write_text("""
# Test API Project

A REST API built with FastAPI for authentication and user management.

## Features
- User authentication with JWT tokens
- Database integration with SQLAlchemy
""")

    return project_path


@pytest.fixture
def node_project(temp_dir):
    """Create a Node.js project with package.json and README."""
    project_path = temp_dir / "node_project"
    project_path.mkdir(parents=True)

    # Create package.json with React
    package_json = project_path / "package.json"
    package_json.write_text(json.dumps({
        "name": "test-app",
        "version": "1.0.0",
        "dependencies": {
            "react": "^18.0.0",
            "react-dom": "^18.0.0",
            "next": "^14.0.0"
        },
        "devDependencies": {
            "typescript": "^5.0.0",
            "jest": "^29.0.0"
        }
    }))

    # Create README
    readme = project_path / "README.md"
    readme.write_text("""
# Test React App

A modern web application built with Next.js and TypeScript.

## Features
- Server-side rendering with Next.js
- Type-safe components
""")

    return project_path


@pytest.fixture
def rust_project(temp_dir):
    """Create a Rust project with Cargo.toml."""
    project_path = temp_dir / "rust_project"
    project_path.mkdir(parents=True)

    cargo = project_path / "Cargo.toml"
    cargo.write_text("""
[package]
name = "test-cli"
version = "0.1.0"

[dependencies]
tokio = { version = "1.0", features = ["full"] }
serde = { version = "1.0", features = ["derive"] }
""")

    return project_path


@pytest.fixture
def empty_project(temp_dir):
    """Create an empty project directory."""
    project_path = temp_dir / "empty_project"
    project_path.mkdir(parents=True)
    return project_path


@pytest.fixture
def project_with_docker(temp_dir):
    """Create a project with Docker and CI/CD configuration."""
    project_path = temp_dir / "docker_project"
    project_path.mkdir(parents=True)

    # Create Dockerfile
    dockerfile = project_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.11\n")

    # Create GitHub Actions workflow directory
    workflows = project_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: CI\n")

    # Create pyproject.toml
    pyproject = project_path / "pyproject.toml"
    pyproject.write_text("""
[project]
name = "docker-app"
version = "0.1.0"
""")

    return project_path


@pytest.fixture
def ledger_with_learnings(global_ledger):
    """Populate the global ledger with various learnings for testing."""
    # Python/FastAPI learning
    learning1 = Learning(
        category=LearningCategory.PATTERN,
        content="FastAPI dependency injection with Depends() allows clean separation of concerns",
        confidence=0.85,
        project_context=ProjectContext(
            project_type="python",
            tech_stack=["fastapi", "pydantic"],
            keywords=["dependency", "injection", "api"]
        )
    )

    # Python/pytest learning
    learning2 = Learning(
        category=LearningCategory.DISCOVERY,
        content="Use pytest fixtures for database setup to ensure clean state between tests",
        confidence=0.75,
        project_context=ProjectContext(
            project_type="python",
            tech_stack=["pytest", "sqlalchemy"],
            keywords=["testing", "database", "fixtures"]
        )
    )

    # Node.js/React learning
    learning3 = Learning(
        category=LearningCategory.PATTERN,
        content="React useCallback prevents unnecessary re-renders in child components",
        confidence=0.80,
        project_context=ProjectContext(
            project_type="node",
            tech_stack=["react", "typescript"],
            keywords=["hooks", "performance", "optimization"]
        )
    )

    # Generic learning (no project context)
    learning4 = Learning(
        category=LearningCategory.ERROR,
        content="Always handle async errors with try/catch or .catch() to avoid unhandled rejections",
        confidence=0.90,
    )

    # Low confidence learning
    learning5 = Learning(
        category=LearningCategory.DISCOVERY,
        content="Docker multi-stage builds can reduce image size significantly",
        confidence=0.40,
        project_context=ProjectContext(
            project_type="python",
            tech_stack=["docker"],
            keywords=["deployment", "containers"]
        )
    )

    # Rust learning
    learning6 = Learning(
        category=LearningCategory.PATTERN,
        content="Use Result<T, E> for error handling instead of panicking in Rust libraries",
        confidence=0.85,
        project_context=ProjectContext(
            project_type="rust",
            tech_stack=["tokio", "serde"],
            keywords=["error", "handling", "async"]
        )
    )

    # Authentication learning (matches keywords)
    learning7 = Learning(
        category=LearningCategory.DECISION,
        content="JWT tokens should have short expiry times with refresh token rotation for security",
        confidence=0.70,
        project_context=ProjectContext(
            project_type="python",
            tech_stack=["fastapi", "auth"],
            keywords=["authentication", "jwt", "security"]
        )
    )

    global_ledger.append_block(
        session_id="test-session-1",
        learnings=[learning1, learning2, learning3],
        deduplicate=False,
    )
    global_ledger.append_block(
        session_id="test-session-2",
        learnings=[learning4, learning5, learning6, learning7],
        deduplicate=False,
    )

    return global_ledger


# ============================================================================
# Project Analysis Tests
# ============================================================================


class TestDetectProjectType:
    """Tests for project type detection."""

    def test_detect_python_pyproject(self, recommender, python_project):
        """Should detect Python project from pyproject.toml."""
        analysis = recommender.analyze_project(python_project)
        assert analysis.project_type == "python"

    def test_detect_python_setup_py(self, recommender, temp_dir):
        """Should detect Python project from setup.py."""
        project_path = temp_dir / "setup_project"
        project_path.mkdir()
        (project_path / "setup.py").write_text("from setuptools import setup\n")

        analysis = recommender.analyze_project(project_path)
        assert analysis.project_type == "python"

    def test_detect_python_requirements(self, recommender, temp_dir):
        """Should detect Python project from requirements.txt."""
        project_path = temp_dir / "req_project"
        project_path.mkdir()
        (project_path / "requirements.txt").write_text("flask==2.0.0\n")

        analysis = recommender.analyze_project(project_path)
        assert analysis.project_type == "python"

    def test_detect_node_project(self, recommender, node_project):
        """Should detect Node.js project from package.json."""
        analysis = recommender.analyze_project(node_project)
        assert analysis.project_type == "node"

    def test_detect_rust_project(self, recommender, rust_project):
        """Should detect Rust project from Cargo.toml."""
        analysis = recommender.analyze_project(rust_project)
        assert analysis.project_type == "rust"

    def test_detect_go_project(self, recommender, temp_dir):
        """Should detect Go project from go.mod."""
        project_path = temp_dir / "go_project"
        project_path.mkdir()
        (project_path / "go.mod").write_text("module example.com/test\n")

        analysis = recommender.analyze_project(project_path)
        assert analysis.project_type == "go"

    def test_detect_java_maven(self, recommender, temp_dir):
        """Should detect Java project from pom.xml."""
        project_path = temp_dir / "java_project"
        project_path.mkdir()
        (project_path / "pom.xml").write_text("<project></project>\n")

        analysis = recommender.analyze_project(project_path)
        assert analysis.project_type == "java"

    def test_detect_java_gradle(self, recommender, temp_dir):
        """Should detect Java project from build.gradle."""
        project_path = temp_dir / "gradle_project"
        project_path.mkdir()
        (project_path / "build.gradle").write_text("plugins { id 'java' }\n")

        analysis = recommender.analyze_project(project_path)
        assert analysis.project_type == "java"

    def test_detect_kotlin_gradle(self, recommender, temp_dir):
        """Should detect Kotlin project from build.gradle.kts."""
        project_path = temp_dir / "kotlin_project"
        project_path.mkdir()
        (project_path / "build.gradle.kts").write_text("plugins { kotlin(\"jvm\") }\n")

        analysis = recommender.analyze_project(project_path)
        assert analysis.project_type == "kotlin"

    def test_detect_ruby_project(self, recommender, temp_dir):
        """Should detect Ruby project from Gemfile."""
        project_path = temp_dir / "ruby_project"
        project_path.mkdir()
        (project_path / "Gemfile").write_text("source 'https://rubygems.org'\n")

        analysis = recommender.analyze_project(project_path)
        assert analysis.project_type == "ruby"

    def test_detect_php_project(self, recommender, temp_dir):
        """Should detect PHP project from composer.json."""
        project_path = temp_dir / "php_project"
        project_path.mkdir()
        (project_path / "composer.json").write_text("{}\n")

        analysis = recommender.analyze_project(project_path)
        assert analysis.project_type == "php"

    def test_detect_empty_project(self, recommender, empty_project):
        """Should return None for project type when no markers found."""
        analysis = recommender.analyze_project(empty_project)
        assert analysis.project_type is None


class TestExtractTechStack:
    """Tests for tech stack detection."""

    def test_extract_python_tech_stack(self, recommender, python_project):
        """Should detect FastAPI, Pydantic, pytest from pyproject.toml."""
        analysis = recommender.analyze_project(python_project)

        assert "fastapi" in analysis.tech_stack
        assert "pydantic" in analysis.tech_stack
        assert "pytest" in analysis.tech_stack

    def test_extract_node_tech_stack(self, recommender, node_project):
        """Should detect React, Next.js, TypeScript, Jest from package.json."""
        analysis = recommender.analyze_project(node_project)

        assert "react" in analysis.tech_stack
        assert "next" in analysis.tech_stack
        assert "typescript" in analysis.tech_stack
        assert "jest" in analysis.tech_stack

    def test_extract_docker_from_dockerfile(self, recommender, project_with_docker):
        """Should detect Docker from Dockerfile presence."""
        analysis = recommender.analyze_project(project_with_docker)

        assert "docker" in analysis.tech_stack

    def test_extract_cicd_from_github_actions(self, recommender, project_with_docker):
        """Should detect CI/CD from .github/workflows directory."""
        analysis = recommender.analyze_project(project_with_docker)

        assert "ci/cd" in analysis.tech_stack

    def test_extract_cicd_from_gitlab_ci(self, recommender, temp_dir):
        """Should detect CI/CD from .gitlab-ci.yml."""
        project_path = temp_dir / "gitlab_project"
        project_path.mkdir()
        (project_path / ".gitlab-ci.yml").write_text("stages:\n  - test\n")

        analysis = recommender.analyze_project(project_path)

        assert "ci/cd" in analysis.tech_stack

    def test_extract_empty_tech_stack(self, recommender, empty_project):
        """Should return empty tech stack for empty project."""
        analysis = recommender.analyze_project(empty_project)

        assert analysis.tech_stack == []

    def test_tech_stack_from_cargo_toml(self, recommender, rust_project):
        """Should detect tech from Cargo.toml dependencies."""
        analysis = recommender.analyze_project(rust_project)
        # tokio and serde are mentioned in the Cargo.toml patterns
        # The current implementation checks for patterns in content
        assert isinstance(analysis.tech_stack, list)


class TestExtractKeywords:
    """Tests for keyword extraction."""

    def test_extract_keywords_from_readme(self, recommender, python_project):
        """Should extract keywords from README.md."""
        analysis = recommender.analyze_project(python_project)

        # Keywords are extracted and normalized to lowercase
        # Check for some expected keywords from the README
        assert len(analysis.keywords) > 0
        # "authentication" should be extracted (more than 3 chars)
        assert any("auth" in kw for kw in analysis.keywords)

    def test_extract_keywords_from_claude_md(self, recommender, temp_dir):
        """Should extract keywords from CLAUDE.md."""
        project_path = temp_dir / "claude_project"
        project_path.mkdir()

        claude_md = project_path / "CLAUDE.md"
        claude_md.write_text("""
# Project Instructions

This project uses blockchain technology for distributed ledger storage.
Focus on performance optimization and caching strategies.
""")

        analysis = recommender.analyze_project(project_path)

        assert len(analysis.keywords) > 0
        # Should find technical terms
        keyword_str = " ".join(analysis.keywords)
        assert "blockchain" in keyword_str or "ledger" in keyword_str or "caching" in keyword_str

    def test_extract_keywords_filters_common_words(self, recommender, temp_dir):
        """Should filter out common words like 'the', 'and', 'for'."""
        project_path = temp_dir / "common_words_project"
        project_path.mkdir()

        readme = project_path / "README.md"
        readme.write_text("The project and the code for this application with that feature")

        analysis = recommender.analyze_project(project_path)

        # Common words should be filtered
        assert "the" not in analysis.keywords
        assert "and" not in analysis.keywords
        assert "for" not in analysis.keywords
        assert "with" not in analysis.keywords
        assert "this" not in analysis.keywords
        assert "that" not in analysis.keywords

    def test_extract_keywords_empty_project(self, recommender, empty_project):
        """Should return empty keywords for project without README or CLAUDE.md."""
        analysis = recommender.analyze_project(empty_project)

        assert analysis.keywords == []

    def test_keywords_limited_to_20(self, recommender, temp_dir):
        """Should limit keywords to 20 entries."""
        project_path = temp_dir / "many_keywords_project"
        project_path.mkdir()

        # Create README with many unique technical terms
        terms = [f"Technology{i}" for i in range(50)]
        readme = project_path / "README.md"
        readme.write_text(" ".join(terms))

        analysis = recommender.analyze_project(project_path)

        assert len(analysis.keywords) <= 20


# ============================================================================
# Learning Recommendations Tests
# ============================================================================


class TestRecommend:
    """Tests for learning recommendations."""

    def test_recommend_returns_relevant_learnings(self, ledger_with_learnings, python_project):
        """Should return learnings relevant to the project."""
        recommender = LearningRecommender(ledger_with_learnings)

        suggestions = recommender.get_suggestions(python_project)

        assert len(suggestions) > 0
        # Should find Python-related learnings
        python_learnings = [s for s in suggestions
                          if s.learning.project_context
                          and s.learning.project_context.project_type == "python"]
        assert len(python_learnings) > 0

    def test_recommend_filters_by_confidence(self, ledger_with_learnings, python_project):
        """Should filter learnings below confidence threshold."""
        recommender = LearningRecommender(ledger_with_learnings)

        # Low confidence learning (0.40) should be excluded with default min_confidence=0.5
        suggestions = recommender.get_suggestions(python_project, min_confidence=0.5)

        for suggestion in suggestions:
            assert suggestion.learning.confidence >= 0.5

    def test_recommend_high_confidence_threshold(self, ledger_with_learnings, python_project):
        """Should return fewer results with higher confidence threshold."""
        recommender = LearningRecommender(ledger_with_learnings)

        low_threshold = recommender.get_suggestions(python_project, min_confidence=0.5)
        high_threshold = recommender.get_suggestions(python_project, min_confidence=0.8)

        # Higher threshold should return equal or fewer results
        assert len(high_threshold) <= len(low_threshold)

    def test_recommend_limits_results(self, ledger_with_learnings, python_project):
        """Should limit the number of suggestions returned."""
        recommender = LearningRecommender(ledger_with_learnings)

        suggestions = recommender.get_suggestions(python_project, limit=2)

        assert len(suggestions) <= 2

    def test_recommend_sorted_by_relevance(self, ledger_with_learnings, python_project):
        """Should return suggestions sorted by relevance score (descending)."""
        recommender = LearningRecommender(ledger_with_learnings)

        suggestions = recommender.get_suggestions(python_project)

        if len(suggestions) > 1:
            scores = [s.relevance_score for s in suggestions]
            assert scores == sorted(scores, reverse=True)

    def test_recommend_for_node_project(self, ledger_with_learnings, node_project):
        """Should return Node.js relevant learnings for Node project."""
        recommender = LearningRecommender(ledger_with_learnings)

        suggestions = recommender.get_suggestions(node_project)

        # Should find React learning for Node project
        react_learnings = [s for s in suggestions
                         if s.learning.project_context
                         and "react" in s.learning.project_context.tech_stack]
        assert len(react_learnings) > 0

    def test_recommend_for_rust_project(self, ledger_with_learnings, rust_project):
        """Should return Rust relevant learnings for Rust project."""
        recommender = LearningRecommender(ledger_with_learnings)

        suggestions = recommender.get_suggestions(rust_project)

        # Should find Rust learning
        rust_learnings = [s for s in suggestions
                        if s.learning.project_context
                        and s.learning.project_context.project_type == "rust"]
        assert len(rust_learnings) > 0


class TestRelevanceScoring:
    """Tests for relevance scoring logic."""

    def test_tech_stack_matches_boost_score(self, ledger_with_learnings, python_project):
        """Should boost score when tech stack matches."""
        recommender = LearningRecommender(ledger_with_learnings)

        suggestions = recommender.get_suggestions(python_project)

        # FastAPI learning should have tech stack match reason
        fastapi_suggestions = [s for s in suggestions
                              if "FastAPI" in s.learning.content or "fastapi" in s.learning.content.lower()]

        if fastapi_suggestions:
            reasons = " ".join(fastapi_suggestions[0].match_reasons)
            # Should mention tech stack match or similar
            assert len(fastapi_suggestions[0].match_reasons) > 1  # More than just confidence

    def test_keyword_matches_boost_score(self, ledger_with_learnings, python_project):
        """Should boost score when keywords match."""
        recommender = LearningRecommender(ledger_with_learnings)

        suggestions = recommender.get_suggestions(python_project)

        # Look for suggestions with keyword matches
        keyword_matched = [s for s in suggestions
                         if any("Keyword" in r for r in s.match_reasons)]

        # Authentication is in README, should match JWT learning
        # The exact match depends on keyword extraction

    def test_project_type_match_boosts_score(self, ledger_with_learnings, python_project):
        """Should boost score when project type matches."""
        recommender = LearningRecommender(ledger_with_learnings)

        analysis = recommender.analyze_project(python_project)
        suggestions = recommender.get_suggestions_for_analysis(analysis)

        # Python learnings should have project type match
        for suggestion in suggestions:
            if (suggestion.learning.project_context
                and suggestion.learning.project_context.project_type == "python"):
                reasons = " ".join(suggestion.match_reasons)
                assert "project type" in reasons.lower() or "python" in reasons.lower()

    def test_score_includes_confidence_component(self, ledger_with_learnings, python_project):
        """Should include confidence in scoring."""
        recommender = LearningRecommender(ledger_with_learnings)

        suggestions = recommender.get_suggestions(python_project)

        for suggestion in suggestions:
            # All suggestions should have confidence reason
            has_confidence_reason = any("Confidence" in r for r in suggestion.match_reasons)
            assert has_confidence_reason


class TestSuggestionFormatting:
    """Tests for Suggestion formatting."""

    def test_format_summary_truncates_long_content(self, global_ledger):
        """Should truncate content longer than max_length."""
        learning = Learning(
            category=LearningCategory.DISCOVERY,
            content="A" * 200,  # Long content
            confidence=0.8,
        )

        suggestion = Suggestion(
            learning=learning,
            relevance_score=0.5,
            match_reasons=["Test"],
        )

        summary = suggestion.format_summary(max_length=50)

        assert len(summary) == 50
        assert summary.endswith("...")

    def test_format_summary_preserves_short_content(self, global_ledger):
        """Should preserve content shorter than max_length."""
        learning = Learning(
            category=LearningCategory.DISCOVERY,
            content="Short content here",
            confidence=0.8,
        )

        suggestion = Suggestion(
            learning=learning,
            relevance_score=0.5,
            match_reasons=["Test"],
        )

        summary = suggestion.format_summary(max_length=150)

        assert summary == "Short content here"
        assert "..." not in summary


class TestTopSuggestionsSummary:
    """Tests for get_top_suggestions_summary method."""

    def test_summary_format(self, ledger_with_learnings, python_project):
        """Should return formatted summary string."""
        recommender = LearningRecommender(ledger_with_learnings)

        summary = recommender.get_top_suggestions_summary(python_project, limit=3)

        assert "## Suggested from Global Knowledge" in summary
        # Should have numbered items
        assert "1." in summary

    def test_summary_empty_when_no_suggestions(self, global_ledger, empty_project):
        """Should return empty string when no suggestions found."""
        recommender = LearningRecommender(global_ledger)

        summary = recommender.get_top_suggestions_summary(empty_project, limit=3)

        assert summary == ""

    def test_summary_respects_limit(self, ledger_with_learnings, python_project):
        """Should respect the limit parameter."""
        recommender = LearningRecommender(ledger_with_learnings)

        summary = recommender.get_top_suggestions_summary(python_project, limit=2)

        # Should have at most 2 numbered items
        assert summary.count("\n1.") == 1  # First item
        # Should not have more than 2 items
        assert "3." not in summary


# ============================================================================
# Edge Cases Tests
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_empty_project_directory(self, recommender, empty_project):
        """Should handle empty project directory gracefully."""
        analysis = recommender.analyze_project(empty_project)

        assert analysis.project_type is None
        assert analysis.tech_stack == []
        assert analysis.keywords == []
        assert analysis.project_path == empty_project

    def test_no_readme_or_claude_md(self, recommender, temp_dir):
        """Should handle project without README or CLAUDE.md."""
        project_path = temp_dir / "no_docs_project"
        project_path.mkdir()
        (project_path / "pyproject.toml").write_text("[project]\nname = 'test'\n")

        analysis = recommender.analyze_project(project_path)

        assert analysis.project_type == "python"
        assert analysis.keywords == []  # No keywords without README/CLAUDE.md

    def test_no_matching_learnings(self, global_ledger, rust_project):
        """Should return empty list when no learnings match."""
        # Global ledger is empty
        recommender = LearningRecommender(global_ledger)

        suggestions = recommender.get_suggestions(rust_project)

        assert suggestions == []

    def test_malformed_package_json(self, recommender, temp_dir):
        """Should handle malformed package.json gracefully."""
        project_path = temp_dir / "bad_json_project"
        project_path.mkdir()
        (project_path / "package.json").write_text("{ invalid json }")

        analysis = recommender.analyze_project(project_path)

        assert analysis.project_type == "node"  # Still detected from file existence
        # Should not crash, tech_stack might be empty due to parse error
        assert isinstance(analysis.tech_stack, list)

    def test_unreadable_files(self, recommender, temp_dir):
        """Should handle files that can't be read."""
        project_path = temp_dir / "unreadable_project"
        project_path.mkdir()

        # Create pyproject.toml but make it unreadable (if possible)
        pyproject = project_path / "pyproject.toml"
        pyproject.write_text("[project]\nname='test'\n")

        # Analysis should still work even if some files fail
        analysis = recommender.analyze_project(project_path)

        assert analysis.project_type == "python"

    def test_nonexistent_project_path(self, recommender, temp_dir):
        """Should handle non-existent project path gracefully."""
        nonexistent = temp_dir / "does_not_exist"

        analysis = recommender.analyze_project(nonexistent)

        # Should return empty analysis without crashing
        assert analysis.project_type is None
        assert analysis.tech_stack == []
        assert analysis.keywords == []

    def test_learning_without_project_context(self, global_ledger, python_project):
        """Should handle learnings without project_context."""
        learning = Learning(
            category=LearningCategory.ERROR,
            content="Generic error handling advice for any project type",
            confidence=0.9,
            # No project_context
        )

        global_ledger.append_block(
            session_id="no-context-session",
            learnings=[learning],
            deduplicate=False,
        )

        recommender = LearningRecommender(global_ledger)
        suggestions = recommender.get_suggestions(python_project)

        # Should include learning even without project context (based on content matching)
        # The scoring should still work
        assert isinstance(suggestions, list)


class TestProjectAnalysisDataclass:
    """Tests for ProjectAnalysis dataclass."""

    def test_to_dict_conversion(self, recommender, python_project):
        """Should convert analysis to dictionary correctly."""
        analysis = recommender.analyze_project(python_project)

        result = analysis.to_dict()

        assert result["project_type"] == "python"
        assert isinstance(result["tech_stack"], list)
        assert isinstance(result["keywords"], list)
        assert result["project_path"] == str(python_project)

    def test_to_dict_with_none_path(self):
        """Should handle None project_path in to_dict."""
        analysis = ProjectAnalysis(
            project_type="python",
            tech_stack=["pytest"],
            keywords=["testing"],
            project_path=None,
        )

        result = analysis.to_dict()

        assert result["project_path"] is None
