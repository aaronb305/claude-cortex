"""Pull request extraction for learning ingestion."""

from datetime import datetime
from typing import Optional

from claude_cortex.ledger.models import (
    Learning,
    LearningCategory,
    LearningSource,
    GitSourceMetadata,
    PrivacyLevel,
)
from claude_cortex.ingest.github_client import (
    GitHubClient,
    PullRequest,
    Review,
    Comment,
)
from claude_cortex.ingest.patterns import (
    EXPLICIT_TAG_PATTERNS,
    PR_INSIGHT_PATTERNS,
    MIN_MESSAGE_LENGTH,
    CONFIDENCE_EXPLICIT_TAG,
    CONFIDENCE_PR_DESCRIPTION,
    CONFIDENCE_PR_REVIEW,
)


class PRExtractor:
    """Extracts learnings from GitHub pull requests."""

    def __init__(self, client: GitHubClient):
        """Initialize PR extractor.

        Args:
            client: GitHub client for API access
        """
        self.client = client

    def extract_from_pr(
        self,
        pr: PullRequest,
        include_reviews: bool = True,
        include_comments: bool = True,
    ) -> list[Learning]:
        """Extract learnings from a pull request.

        Args:
            pr: The pull request to extract from
            include_reviews: Whether to extract from review comments
            include_comments: Whether to extract from discussion comments

        Returns:
            List of Learning objects
        """
        learnings = []

        # Extract from PR description
        learnings.extend(self._extract_from_description(pr))

        # Extract from reviews
        if include_reviews:
            reviews = self.client.get_pr_reviews(pr.number)
            for review in reviews:
                learnings.extend(self._extract_from_review(pr, review))

        # Extract from inline code comments
        if include_comments:
            comments = self.client.get_pr_comments(pr.number)
            for comment in comments:
                learnings.extend(self._extract_from_comment(pr, comment))

            # Also get discussion comments
            discussion = self.client.get_pr_discussion_comments(pr.number)
            for comment in discussion:
                learnings.extend(self._extract_from_comment(pr, comment))

        return learnings

    def _create_git_metadata(
        self,
        pr: PullRequest,
        source: LearningSource,
        review_author: Optional[str] = None,
    ) -> GitSourceMetadata:
        """Create git metadata for a PR-sourced learning.

        Args:
            pr: The pull request
            source: The learning source type
            review_author: Author of the review/comment (if applicable)

        Returns:
            GitSourceMetadata object
        """
        return GitSourceMetadata(
            pr_number=pr.number,
            pr_title=pr.title,
            pr_author=pr.author,
            pr_url=pr.url,
            branch=pr.head_branch,
            review_author=review_author,
        )

    def _extract_from_description(self, pr: PullRequest) -> list[Learning]:
        """Extract learnings from PR description.

        Args:
            pr: The pull request

        Returns:
            List of Learning objects
        """
        learnings = []
        body = pr.body

        if not body or len(body) < MIN_MESSAGE_LENGTH:
            return learnings

        git_metadata = self._create_git_metadata(pr, LearningSource.PR_DESCRIPTION)

        # 1. Check for explicit tags first
        for category, pattern in EXPLICIT_TAG_PATTERNS.items():
            matches = pattern.findall(body)
            for match in matches:
                content = match.strip()
                if len(content) < MIN_MESSAGE_LENGTH:
                    continue

                learning = Learning(
                    category=category,
                    content=content,
                    confidence=CONFIDENCE_EXPLICIT_TAG,
                    source=f"pr:{pr.number}",
                    learning_source=LearningSource.PR_DESCRIPTION,
                    git_metadata=git_metadata,
                    privacy=PrivacyLevel.PUBLIC,
                )
                learnings.append(learning)

        # 2. Extract from structured sections (Why/Motivation, Breaking Changes)
        why_match = PR_INSIGHT_PATTERNS["why_changed"].search(body)
        if why_match:
            content = why_match.group(1).strip()
            if len(content) >= MIN_MESSAGE_LENGTH:
                learning = Learning(
                    category=LearningCategory.DECISION,
                    content=f"[{pr.title}] {content}",
                    confidence=CONFIDENCE_PR_DESCRIPTION,
                    source=f"pr:{pr.number}",
                    learning_source=LearningSource.PR_DESCRIPTION,
                    git_metadata=git_metadata,
                    privacy=PrivacyLevel.PUBLIC,
                )
                learnings.append(learning)

        breaking_match = PR_INSIGHT_PATTERNS["breaking_changes"].search(body)
        if breaking_match:
            content = breaking_match.group(1).strip()
            if len(content) >= MIN_MESSAGE_LENGTH:
                learning = Learning(
                    category=LearningCategory.ERROR,  # Breaking changes are gotchas
                    content=f"[Breaking Change] {content}",
                    confidence=CONFIDENCE_PR_DESCRIPTION + 0.05,  # Boost for breaking
                    source=f"pr:{pr.number}",
                    learning_source=LearningSource.PR_DESCRIPTION,
                    git_metadata=git_metadata,
                    privacy=PrivacyLevel.PUBLIC,
                )
                learnings.append(learning)

        return learnings

    def _extract_from_review(self, pr: PullRequest, review: Review) -> list[Learning]:
        """Extract learnings from a PR review.

        Args:
            pr: The pull request
            review: The review to extract from

        Returns:
            List of Learning objects
        """
        learnings = []
        body = review.body

        if not body or len(body) < MIN_MESSAGE_LENGTH:
            return learnings

        git_metadata = self._create_git_metadata(
            pr, LearningSource.PR_REVIEW, review.author
        )

        # Check for explicit tags
        for category, pattern in EXPLICIT_TAG_PATTERNS.items():
            matches = pattern.findall(body)
            for match in matches:
                content = match.strip()
                if len(content) < MIN_MESSAGE_LENGTH:
                    continue

                learning = Learning(
                    category=category,
                    content=content,
                    confidence=CONFIDENCE_EXPLICIT_TAG,
                    source=f"pr:{pr.number}:review",
                    learning_source=LearningSource.PR_REVIEW,
                    git_metadata=git_metadata,
                    privacy=PrivacyLevel.PUBLIC,
                )
                learnings.append(learning)

        # Extract suggestions from CHANGES_REQUESTED reviews
        if review.state == "CHANGES_REQUESTED" and not learnings:
            # The review content itself might be valuable
            learning = Learning(
                category=LearningCategory.ERROR,  # Review feedback = things to avoid
                content=f"[Code Review] {body}",
                confidence=CONFIDENCE_PR_REVIEW,
                source=f"pr:{pr.number}:review",
                learning_source=LearningSource.PR_REVIEW,
                git_metadata=git_metadata,
                privacy=PrivacyLevel.PUBLIC,
            )
            learnings.append(learning)

        return learnings

    def _extract_from_comment(self, pr: PullRequest, comment: Comment) -> list[Learning]:
        """Extract learnings from a PR comment.

        Args:
            pr: The pull request
            comment: The comment to extract from

        Returns:
            List of Learning objects
        """
        learnings = []
        body = comment.body

        if not body or len(body) < MIN_MESSAGE_LENGTH:
            return learnings

        git_metadata = self._create_git_metadata(
            pr, LearningSource.PR_COMMENT, comment.author
        )

        # Only extract from comments with explicit tags
        for category, pattern in EXPLICIT_TAG_PATTERNS.items():
            matches = pattern.findall(body)
            for match in matches:
                content = match.strip()
                if len(content) < MIN_MESSAGE_LENGTH:
                    continue

                # Add file context if this is an inline comment
                if comment.path:
                    content = f"[{comment.path}:{comment.line or '?'}] {content}"

                learning = Learning(
                    category=category,
                    content=content,
                    confidence=CONFIDENCE_EXPLICIT_TAG,
                    source=f"pr:{pr.number}:comment",
                    learning_source=LearningSource.PR_COMMENT,
                    git_metadata=git_metadata,
                    privacy=PrivacyLevel.PUBLIC,
                )
                learnings.append(learning)

        return learnings

    def ingest_prs(
        self,
        state: str = "merged",
        limit: int = 50,
        since: Optional[datetime] = None,
        pr_number: Optional[int] = None,
        include_reviews: bool = True,
        include_comments: bool = True,
    ) -> tuple[list[Learning], list[PullRequest]]:
        """Ingest pull requests and extract learnings.

        Args:
            state: PR state filter
            limit: Maximum PRs to process
            since: Only PRs after this date
            pr_number: Specific PR number to process (ignores other filters)
            include_reviews: Extract from reviews
            include_comments: Extract from comments

        Returns:
            Tuple of (learnings extracted, PRs processed)
        """
        if pr_number:
            pr = self.client.get_pr(pr_number)
            if not pr:
                return [], []
            prs = [pr]
        else:
            prs = self.client.list_prs(state=state, limit=limit, since=since)

        all_learnings = []
        for pr in prs:
            learnings = self.extract_from_pr(
                pr,
                include_reviews=include_reviews,
                include_comments=include_comments,
            )
            all_learnings.extend(learnings)

        return all_learnings, prs
