from typing import Any, List, Optional
import os
import logging
import time
import jwt
import requests
from github import Github

logger = logging.getLogger(__name__)


class GitHubClient:
    def __init__(self, token: Optional[str] = None):
        """Initialize client.

        Behavior:
        - If token (or env GITHUB_TOKEN) is provided, use it (PAT flow).
        - Else, if GITHUB_APP_ID and GITHUB_PRIVATE_KEY_PATH are provided, use GitHub App flow:
            - generate a short-lived JWT and exchange for an installation token for a given installation id.
        """
        self._pat = token or os.getenv("GITHUB_TOKEN")
        self.app_id = os.getenv("GITHUB_APP_ID")
        self.private_key_path = os.getenv("GITHUB_PRIVATE_KEY_PATH")
        self._gh: Optional[Github] = None
        self._installation_token: Optional[str] = None
        self._installation_token_expires_at: Optional[float] = None
        if self._pat:
            self._gh = Github(self._pat)

    def _init_with_installation_token(self, owner: str, repo: str):
        # If we already have a valid installation token, use it
        token_valid = (
            self._installation_token
            and self._installation_token_expires_at
            and time.time() < self._installation_token_expires_at - 30
        )
        if token_valid:
            if not self._gh:
                self._gh = Github(self._installation_token)
            return

        if not (self.app_id and self.private_key_path):
            raise ValueError("GITHUB_APP_ID and GITHUB_PRIVATE_KEY_PATH required for GitHub App auth")

        # Load private key
        with open(self.private_key_path, "r") as f:
            private_key = f.read()

        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + (9 * 60),
            "iss": str(self.app_id),
        }
        jwt_token = jwt.encode(payload, private_key, algorithm="RS256")

        # Find installation id for owner/repo via API
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github+json",
        }
        # GET /repos/{owner}/{repo}/installation
        url = f"https://api.github.com/repos/{owner}/{repo}/installation"
        r = requests.get(url, headers=headers)
        if r.status_code != 200:
            raise RuntimeError(f"Failed to find installation for {owner}/{repo}: {r.status_code} {r.text}")
        installation = r.json()
        installation_id = installation.get("id")

        # Create an installation access token
        token_url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        r2 = requests.post(token_url, headers=headers)
        if r2.status_code != 201:
            raise RuntimeError(f"Failed to create installation token: {r2.status_code} {r2.text}")
        data = r2.json()
        self._installation_token = data["token"]
        # The API returns an ISO timestamp; we use a fixed 9-minute fallback
        self._installation_token_expires_at = time.time() + 9 * 60
        self._gh = Github(self._installation_token)

    def _ensure_gh(self, owner: str, repo: str):
        if self._gh:
            return
        # Initialize via GitHub App flow
        self._init_with_installation_token(owner, repo)

    def fetch_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """Return unified diff for the PR using PyGithub."""
        if not self._gh:
            self._ensure_gh(owner, repo)
        repository = self._gh.get_repo(f"{owner}/{repo}")
        pr = repository.get_pull(pr_number)
        self._last_head_sha: Optional[str] = pr.head.sha
        return pr.patch or ""

    def fetch_file_content(self, owner: str, repo: str, path: str, ref: str) -> List[str]:
        """Return file lines at the given git ref, or [] on any error (binary, missing, etc.)."""
        try:
            if not self._gh:
                self._ensure_gh(owner, repo)
            repository = self._gh.get_repo(f"{owner}/{repo}")
            contents = repository.get_contents(path, ref=ref)
            text = contents.decoded_content.decode('utf-8', errors='replace')
            return text.splitlines()
        except Exception:
            logger.warning('Could not fetch file content for %s at %s', path, ref)
            return []

    def fetch_reviewbot_config(self, owner: str, repo: str, ref: str):
        """Return a ReviewConfig parsed from .reviewbot.yml at ref, or defaults if absent/invalid."""
        from pr_pilot.config import ReviewConfig
        lines = self.fetch_file_content(owner, repo, '.reviewbot.yml', ref)
        if not lines:
            return ReviewConfig()
        try:
            import yaml
            data = yaml.safe_load('\n'.join(lines)) or {}
            if isinstance(data, dict):
                return ReviewConfig.from_dict(data)
        except Exception:
            logger.warning('Failed to parse .reviewbot.yml for %s/%s@%s', owner, repo, ref)
        return ReviewConfig()

    def post_issue_comment(self, owner: str, repo: str, pr_number: int, body: str) -> Any:
        """Post a plain (non-review) comment on the PR — visible immediately, no position needed."""
        if not self._gh:
            self._ensure_gh(owner, repo)
        repository = self._gh.get_repo(f"{owner}/{repo}")
        issue = repository.get_issue(pr_number)
        return issue.create_comment(body)

    def post_review(
        self, owner: str, repo: str, pr_number: int,
        comments: list[dict], body: str = "",
    ) -> Any:
        """Post a single review with inline comments.

        comments: list of {'path': str, 'position': int, 'body': str}
        body: top-level review body (markdown summary).
        """
        if not self._gh:
            self._ensure_gh(owner, repo)
        repository = self._gh.get_repo(f"{owner}/{repo}")
        pr = repository.get_pull(pr_number)
        return pr.create_review(
            event="COMMENT",
            body=body or "Automated review from pr-pilot",
            comments=comments,
        )
