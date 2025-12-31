"""GitHub client using gh CLI for PR/issue access."""

import json
import subprocess
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional


@dataclass
class PullRequest:
    """Represents a GitHub pull request."""

    number: int
    title: str
    body: str
    author: str
    url: str
    merged_at: Optional[datetime]
    labels: list[str]
    base_branch: str
    head_branch: str


@dataclass
class Review:
    """Represents a PR review."""

    author: str
    body: str
    state: str  # APPROVED, CHANGES_REQUESTED, COMMENTED


@dataclass
class Comment:
    """Represents a PR comment."""

    author: str
    body: str
    path: Optional[str]  # File path for review comments
    line: Optional[int]  # Line number for review comments


class RateLimiter:
    """Simple rate limiter for gh CLI calls."""

    def __init__(self, calls_per_minute: int = 30):
        self.calls_per_minute = calls_per_minute
        self.call_times: list[datetime] = []

    def wait_if_needed(self) -> None:
        """Block if we've exceeded rate limit."""
        now = datetime.now(timezone.utc)
        minute_ago = now - timedelta(minutes=1)

        # Remove old calls
        self.call_times = [t for t in self.call_times if t > minute_ago]

        if len(self.call_times) >= self.calls_per_minute:
            # Wait until oldest call expires
            sleep_time = (self.call_times[0] - minute_ago).total_seconds()
            if sleep_time > 0:
                time.sleep(sleep_time)

        self.call_times.append(now)


class GitHubClient:
    """GitHub client using gh CLI."""

    def __init__(self, repo: Optional[str] = None, rate_limit: int = 30):
        """Initialize GitHub client.

        Args:
            repo: Repository in owner/repo format. If None, detected from git remote.
            rate_limit: Maximum API calls per minute
        """
        self.repo = repo or self._detect_repo()
        self.rate_limiter = RateLimiter(rate_limit)
        self._verify_auth()

    def _verify_auth(self) -> None:
        """Check if gh is authenticated."""
        result = subprocess.run(
            ["gh", "auth", "status"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(
                "gh CLI not authenticated. Run: gh auth login\n"
                f"Error: {result.stderr}"
            )

    def _detect_repo(self) -> str:
        """Detect GitHub repo from git remote."""
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError("Could not detect repository from git remote")

        url = result.stdout.strip()

        # Parse GitHub URL formats:
        # https://github.com/owner/repo.git
        # git@github.com:owner/repo.git
        patterns = [
            r"github\.com[:/]([^/]+)/([^/.]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return f"{match.group(1)}/{match.group(2)}"

        raise RuntimeError(f"Could not parse GitHub repo from URL: {url}")

    def _run_gh(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a gh command with rate limiting.

        Args:
            *args: gh command arguments
            check: Whether to raise on non-zero exit

        Returns:
            CompletedProcess with stdout/stderr
        """
        self.rate_limiter.wait_if_needed()
        cmd = ["gh"] + list(args)
        return subprocess.run(cmd, capture_output=True, text=True, check=check)

    def list_prs(
        self,
        state: str = "merged",
        limit: int = 50,
        since: Optional[datetime] = None,
        author: Optional[str] = None,
        label: Optional[str] = None,
    ) -> list[PullRequest]:
        """List pull requests.

        Args:
            state: PR state - open, closed, merged, all
            limit: Maximum PRs to return
            since: Only PRs updated after this date
            author: Filter by author
            label: Filter by label

        Returns:
            List of PullRequest objects
        """
        cmd = [
            "pr", "list",
            "--repo", self.repo,
            "--state", state,
            "--limit", str(limit),
            "--json", "number,title,body,author,url,mergedAt,labels,baseRefName,headRefName",
        ]

        if author:
            cmd.extend(["--author", author])
        if label:
            cmd.extend(["--label", label])

        result = self._run_gh(*cmd, check=False)
        if result.returncode != 0:
            return []

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []

        prs = []
        for item in data:
            merged_at = None
            if item.get("mergedAt"):
                try:
                    merged_at = datetime.fromisoformat(
                        item["mergedAt"].replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            # Filter by since date
            if since and merged_at and merged_at < since:
                continue

            pr = PullRequest(
                number=item["number"],
                title=item["title"],
                body=item.get("body") or "",
                author=item["author"]["login"] if item.get("author") else "",
                url=item["url"],
                merged_at=merged_at,
                labels=[l["name"] for l in item.get("labels", [])],
                base_branch=item.get("baseRefName", ""),
                head_branch=item.get("headRefName", ""),
            )
            prs.append(pr)

        return prs

    def get_pr(self, pr_number: int) -> Optional[PullRequest]:
        """Get a specific pull request.

        Args:
            pr_number: The PR number

        Returns:
            PullRequest or None if not found
        """
        cmd = [
            "pr", "view", str(pr_number),
            "--repo", self.repo,
            "--json", "number,title,body,author,url,mergedAt,labels,baseRefName,headRefName",
        ]

        result = self._run_gh(*cmd, check=False)
        if result.returncode != 0:
            return None

        try:
            item = json.loads(result.stdout)
        except json.JSONDecodeError:
            return None

        merged_at = None
        if item.get("mergedAt"):
            try:
                merged_at = datetime.fromisoformat(
                    item["mergedAt"].replace("Z", "+00:00")
                )
            except ValueError:
                pass

        return PullRequest(
            number=item["number"],
            title=item["title"],
            body=item.get("body") or "",
            author=item["author"]["login"] if item.get("author") else "",
            url=item["url"],
            merged_at=merged_at,
            labels=[l["name"] for l in item.get("labels", [])],
            base_branch=item.get("baseRefName", ""),
            head_branch=item.get("headRefName", ""),
        )

    def get_pr_reviews(self, pr_number: int) -> list[Review]:
        """Get reviews for a PR.

        Args:
            pr_number: The PR number

        Returns:
            List of Review objects
        """
        cmd = [
            "api",
            f"repos/{self.repo}/pulls/{pr_number}/reviews",
            "--jq", ".[] | {author: .user.login, body: .body, state: .state}",
        ]

        result = self._run_gh(*cmd, check=False)
        if result.returncode != 0:
            return []

        reviews = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("body"):  # Only include reviews with content
                    reviews.append(
                        Review(
                            author=data.get("author", ""),
                            body=data["body"],
                            state=data.get("state", ""),
                        )
                    )
            except json.JSONDecodeError:
                pass

        return reviews

    def get_pr_comments(self, pr_number: int) -> list[Comment]:
        """Get review comments for a PR (inline code comments).

        Args:
            pr_number: The PR number

        Returns:
            List of Comment objects
        """
        cmd = [
            "api",
            f"repos/{self.repo}/pulls/{pr_number}/comments",
            "--jq", ".[] | {author: .user.login, body: .body, path: .path, line: .line}",
        ]

        result = self._run_gh(*cmd, check=False)
        if result.returncode != 0:
            return []

        comments = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("body"):
                    comments.append(
                        Comment(
                            author=data.get("author", ""),
                            body=data["body"],
                            path=data.get("path"),
                            line=data.get("line"),
                        )
                    )
            except json.JSONDecodeError:
                pass

        return comments

    def get_pr_discussion_comments(self, pr_number: int) -> list[Comment]:
        """Get discussion comments for a PR (not inline code comments).

        Args:
            pr_number: The PR number

        Returns:
            List of Comment objects
        """
        cmd = [
            "api",
            f"repos/{self.repo}/issues/{pr_number}/comments",
            "--jq", ".[] | {author: .user.login, body: .body}",
        ]

        result = self._run_gh(*cmd, check=False)
        if result.returncode != 0:
            return []

        comments = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            try:
                data = json.loads(line)
                if data.get("body"):
                    comments.append(
                        Comment(
                            author=data.get("author", ""),
                            body=data["body"],
                            path=None,
                            line=None,
                        )
                    )
            except json.JSONDecodeError:
                pass

        return comments
