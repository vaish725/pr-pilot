import os
import logging
from typing import Dict

from pr_pilot.github_client import GitHubClient
from pr_pilot.llm import parse_diff_hunks, analyze_diff

logger = logging.getLogger(__name__)


def process_pr_job(payload: Dict):
    """Process a PR: fetch diff, analyze, prepare comments, and optionally post.

    payload: { owner, repo, pr_number }
    """
    owner = payload.get("owner")
    repo = payload.get("repo")
    pr_number = payload.get("pr_number")
    if not (owner and repo and pr_number):
        logger.error("Invalid payload for process_pr_job: %s", payload)
        return {"error": "invalid payload"}

    token = os.getenv("GITHUB_TOKEN")
    gh = GitHubClient(token=token)
    diff = gh.fetch_pr_diff(owner, repo, pr_number)
    if not diff:
        logger.info("Empty diff for %s/%s#%s", owner, repo, pr_number)
        return {"comments": []}

    files = parse_diff_hunks(diff)
    comments = []
    for file_path, hunks in files.items():
        for hunk in hunks:
            hunk_text = "\n".join(hunk['lines'])
            # Pass repo context so the LLM layer can account tokens and enforce budgets
            repo_id = f"{owner}/{repo}"
            suggestions = analyze_diff(file_path, hunk_text, repo=repo_id)
            position_start = hunk['position_start']
            for idx, line in enumerate(hunk['lines'], start=1):
                if line.startswith('+') and not line.startswith('+++'):
                    github_position = position_start + idx
                    for s in suggestions:
                        if s.get('line') == idx:
                            comments.append({
                                'path': file_path,
                                'position': github_position,
                                'body': (
                                    f"[{s.get('severity')}] {s.get('message')}"
                                    f"\n\nSuggestion: {s.get('suggestion')}"
                                ),
                            })

    if os.getenv('DO_POST') == '1' and comments:
        review = gh.post_review(owner, repo, pr_number, comments)
        logger.info('Posted review %s', getattr(review, 'id', None))
        return {"posted": True, "review_id": getattr(review, 'id', None)}

    return {"posted": False, "comments": comments}
