from typing import Any
import os
from github import Github


class GitHubClient:
    def __init__(self, token: str | None = None):
        # For this scaffold we accept a personal access token via env var GITHUB_TOKEN
        token = token or os.getenv("GITHUB_TOKEN")
        if not token:
            raise ValueError("GITHUB_TOKEN is required for GitHubClient in this scaffold")
        self.gh = Github(token)

    def fetch_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """Return unified diff for the PR using PyGithub."""
        repository = self.gh.get_repo(f"{owner}/{repo}")
        pr = repository.get_pull(pr_number)
        return pr.patch or ""

    def post_review(self, owner: str, repo: str, pr_number: int, comments: list[dict]) -> Any:
        """Post a single review with inline comments.

        comments: list of {'path': str, 'position': int, 'body': str}
        """
        repository = self.gh.get_repo(f"{owner}/{repo}")
        pr = repository.get_pull(pr_number)
        # PyGithub's create_review accepts a list of dicts with keys: path, position, body
        return pr.create_review(event="COMMENT", body="Automated review from pr-pilot", comments=comments)

