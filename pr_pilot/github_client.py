from typing import Any


class GitHubClient:
    def __init__(self, installation_id: int | None = None):
        # Placeholder for authenticated GitHub client (PyGithub or Octokit)
        self.installation_id = installation_id

    def fetch_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """Return unified diff for the PR. Placeholder."""
        return ""

    def post_review(self, owner: str, repo: str, pr_number: int, comments: list[dict]) -> Any:
        """Post a single review with inline comments. Placeholder."""
        return None
