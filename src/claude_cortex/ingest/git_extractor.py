"""Git commit extraction for learning ingestion."""

import subprocess
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from claude_cortex.ledger.models import (
    Learning,
    LearningCategory,
    LearningSource,
    GitSourceMetadata,
    PrivacyLevel,
)
from claude_cortex.ingest.patterns import (
    EXPLICIT_TAG_PATTERNS,
    CONVENTIONAL_COMMIT_PATTERN,
    COMMIT_TYPE_TO_CATEGORY,
    CO_AUTHOR_PATTERN,
    MIN_MESSAGE_LENGTH,
    CONFIDENCE_EXPLICIT_TAG,
    CONFIDENCE_CONVENTIONAL_COMMIT,
    CONFIDENCE_BOOST_DETAILED,
    CONFIDENCE_BOOST_COAUTHORED,
    CONFIDENCE_BOOST_VERY_DETAILED,
)


@dataclass
class GitCommit:
    """Represents a git commit for processing."""

    sha: str
    author_name: str
    author_email: str
    date: datetime
    subject: str
    body: str
    branch: Optional[str] = None

    @property
    def short_sha(self) -> str:
        """Return first 7 characters of SHA."""
        return self.sha[:7]

    @property
    def full_message(self) -> str:
        """Return complete commit message (subject + body)."""
        if self.body:
            return f"{self.subject}\n\n{self.body}"
        return self.subject


class GitExtractor:
    """Extracts learnings from git commits."""

    def __init__(self, repo_path: Path):
        """Initialize git extractor for a repository.

        Args:
            repo_path: Path to the git repository
        """
        self.repo_path = Path(repo_path)
        self._verify_git_repo()

    def _verify_git_repo(self) -> None:
        """Verify that the path is a git repository."""
        git_dir = self.repo_path / ".git"
        if not git_dir.exists():
            raise ValueError(f"Not a git repository: {self.repo_path}")

    def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command in the repository.

        Args:
            *args: Git command arguments
            check: Whether to raise on non-zero exit

        Returns:
            CompletedProcess with stdout/stderr
        """
        cmd = ["git", "-C", str(self.repo_path)] + list(args)
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=check,
        )

    def get_current_branch(self) -> str:
        """Get the current branch name."""
        result = self._run_git("rev-parse", "--abbrev-ref", "HEAD")
        return result.stdout.strip()

    def get_commits(
        self,
        since_sha: Optional[str] = None,
        since_date: Optional[datetime] = None,
        branch: str = "HEAD",
        include_merges: bool = False,
        limit: Optional[int] = None,
        author: Optional[str] = None,
    ) -> list[GitCommit]:
        """Get commits from the repository.

        Args:
            since_sha: Only commits after this SHA
            since_date: Only commits after this date
            branch: Branch to get commits from
            include_merges: Whether to include merge commits
            limit: Maximum number of commits to return
            author: Filter by author email/name

        Returns:
            List of GitCommit objects, newest first
        """
        # Use NUL separator for safe parsing
        format_str = "%H|%an|%ae|%aI|%s%x00%b%x00"
        cmd = ["log", f"--format={format_str}"]

        if since_sha:
            # Check if the SHA is still an ancestor
            if self._is_ancestor(since_sha, branch):
                cmd.append(f"{since_sha}..{branch}")
            else:
                # History was rewritten, fall back to date if available
                if since_date:
                    cmd.extend(["--since", since_date.isoformat()])
                cmd.append(branch)
        elif since_date:
            cmd.extend(["--since", since_date.isoformat()])
            cmd.append(branch)
        else:
            cmd.append(branch)

        if not include_merges:
            cmd.append("--no-merges")

        if limit:
            cmd.extend(["-n", str(limit)])

        if author:
            cmd.extend(["--author", author])

        result = self._run_git(*cmd, check=False)
        if result.returncode != 0:
            return []

        commits = []
        # Split by double NUL (end of each commit entry)
        entries = result.stdout.split("\x00\x00")

        for entry in entries:
            entry = entry.strip()
            if not entry:
                continue

            # Split header and body
            parts = entry.split("\x00", 1)
            if not parts:
                continue

            header = parts[0]
            body = parts[1].strip() if len(parts) > 1 else ""

            # Parse header: SHA|author_name|author_email|date|subject
            header_parts = header.split("|", 4)
            if len(header_parts) < 5:
                continue

            sha, author_name, author_email, date_str, subject = header_parts

            try:
                # Parse ISO format date
                date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except ValueError:
                date = datetime.now(timezone.utc)

            commits.append(
                GitCommit(
                    sha=sha,
                    author_name=author_name,
                    author_email=author_email,
                    date=date,
                    subject=subject,
                    body=body,
                    branch=branch if branch != "HEAD" else self.get_current_branch(),
                )
            )

        return commits

    def _is_ancestor(self, sha: str, branch: str) -> bool:
        """Check if a SHA is an ancestor of a branch."""
        result = self._run_git(
            "merge-base", "--is-ancestor", sha, branch, check=False
        )
        return result.returncode == 0

    def extract_learnings(self, commit: GitCommit) -> list[Learning]:
        """Extract learnings from a single commit.

        Args:
            commit: The commit to extract learnings from

        Returns:
            List of Learning objects extracted from the commit
        """
        learnings = []
        message = commit.full_message

        # Extract co-authors for attribution
        co_authors = self._extract_co_authors(message)

        # Create git metadata for all learnings from this commit
        git_metadata = GitSourceMetadata(
            commit_sha=commit.sha,
            commit_short_sha=commit.short_sha,
            commit_author_name=commit.author_name,
            commit_author_email=commit.author_email,
            commit_date=commit.date,
            commit_subject=commit.subject,
            branch=commit.branch,
            repository=str(self.repo_path),
        )

        # 1. Extract explicit tags first (highest priority)
        explicit_learnings = self._extract_explicit_tags(
            message, git_metadata, co_authors
        )
        learnings.extend(explicit_learnings)

        # 2. Extract from conventional commits (if no explicit tags found)
        if not explicit_learnings:
            conventional_learning = self._extract_conventional_commit(
                commit, git_metadata, co_authors
            )
            if conventional_learning:
                learnings.append(conventional_learning)

        return learnings

    def _extract_explicit_tags(
        self,
        message: str,
        git_metadata: GitSourceMetadata,
        co_authors: list[str],
    ) -> list[Learning]:
        """Extract learnings from explicit [DISCOVERY], [DECISION], etc. tags.

        Args:
            message: The commit message to parse
            git_metadata: Git metadata for the learning
            co_authors: List of co-author emails

        Returns:
            List of Learning objects from explicit tags
        """
        learnings = []

        for category, pattern in EXPLICIT_TAG_PATTERNS.items():
            matches = pattern.findall(message)
            for match in matches:
                content = match.strip()
                if not content or len(content) < MIN_MESSAGE_LENGTH:
                    continue

                # Compute confidence with boosts
                confidence = self._compute_confidence(
                    base=CONFIDENCE_EXPLICIT_TAG,
                    message_length=len(content),
                    has_coauthors=len(co_authors) > 0,
                )

                learning = Learning(
                    category=category,
                    content=content,
                    confidence=confidence,
                    source=f"git:{git_metadata.commit_short_sha}",
                    learning_source=LearningSource.GIT_COMMIT,
                    git_metadata=git_metadata,
                    co_authors=co_authors,
                    privacy=PrivacyLevel.PUBLIC,
                )
                learnings.append(learning)

        return learnings

    def _extract_conventional_commit(
        self,
        commit: GitCommit,
        git_metadata: GitSourceMetadata,
        co_authors: list[str],
    ) -> Optional[Learning]:
        """Extract a learning from a conventional commit.

        Args:
            commit: The commit to extract from
            git_metadata: Git metadata for the learning
            co_authors: List of co-author emails

        Returns:
            A Learning if extractable, None otherwise
        """
        match = CONVENTIONAL_COMMIT_PATTERN.match(commit.subject)
        if not match:
            return None

        commit_type = match.group(1).lower()
        scope = match.group(2)  # May be None
        description = match.group(3)

        # Get category for this commit type
        category = COMMIT_TYPE_TO_CATEGORY.get(commit_type)
        if category is None:
            return None  # Skip style, build, ci, chore

        # Build content from commit message
        if commit.body:
            # Use body if substantial
            content = f"{description}\n\n{commit.body}".strip()
        else:
            content = description

        if len(content) < MIN_MESSAGE_LENGTH:
            return None

        # Add scope context if present
        if scope:
            content = f"[{scope}] {content}"

        # Compute confidence
        confidence = self._compute_confidence(
            base=CONFIDENCE_CONVENTIONAL_COMMIT,
            message_length=len(content),
            has_coauthors=len(co_authors) > 0,
        )

        return Learning(
            category=category,
            content=content,
            confidence=confidence,
            source=f"git:{git_metadata.commit_short_sha}",
            learning_source=LearningSource.GIT_COMMIT,
            git_metadata=git_metadata,
            co_authors=co_authors,
            privacy=PrivacyLevel.PUBLIC,
        )

    def _extract_co_authors(self, message: str) -> list[str]:
        """Extract co-author emails from commit message.

        Args:
            message: The commit message

        Returns:
            List of co-author email addresses
        """
        co_authors = []
        for match in CO_AUTHOR_PATTERN.finditer(message):
            email = match.group(2)
            co_authors.append(email)
        return co_authors

    def _compute_confidence(
        self,
        base: float,
        message_length: int,
        has_coauthors: bool,
    ) -> float:
        """Compute confidence score with adjustments.

        Args:
            base: Base confidence value
            message_length: Length of the content
            has_coauthors: Whether the commit has co-authors

        Returns:
            Adjusted confidence score (clamped to 0.0-1.0)
        """
        confidence = base

        # Boost for detailed messages
        if message_length > 200:
            confidence += CONFIDENCE_BOOST_VERY_DETAILED
        elif message_length > 100:
            confidence += CONFIDENCE_BOOST_DETAILED

        # Boost for co-authored commits (implies review)
        if has_coauthors:
            confidence += CONFIDENCE_BOOST_COAUTHORED

        return min(1.0, confidence)

    def ingest_commits(
        self,
        since_sha: Optional[str] = None,
        since_date: Optional[datetime] = None,
        branch: str = "HEAD",
        include_merges: bool = False,
        limit: Optional[int] = None,
        author: Optional[str] = None,
        tags_only: bool = False,
    ) -> tuple[list[Learning], list[GitCommit]]:
        """Ingest commits and extract learnings.

        Args:
            since_sha: Only commits after this SHA
            since_date: Only commits after this date
            branch: Branch to process
            include_merges: Whether to include merge commits
            limit: Maximum commits to process
            author: Filter by author
            tags_only: Only extract explicit [DISCOVERY] etc. tags

        Returns:
            Tuple of (learnings extracted, commits processed)
        """
        commits = self.get_commits(
            since_sha=since_sha,
            since_date=since_date,
            branch=branch,
            include_merges=include_merges,
            limit=limit,
            author=author,
        )

        all_learnings = []
        for commit in commits:
            learnings = self.extract_learnings(commit)

            if tags_only:
                # Filter to only explicit tag learnings
                learnings = [
                    l for l in learnings
                    if any(
                        tag in (l.git_metadata.commit_subject or "").upper()
                        for tag in ["[DISCOVERY]", "[DECISION]", "[ERROR]", "[PATTERN]"]
                    )
                    or any(
                        tag in l.content.upper()
                        for tag in ["[DISCOVERY]", "[DECISION]", "[ERROR]", "[PATTERN]"]
                    )
                ]

            all_learnings.extend(learnings)

        return all_learnings, commits
