import os
import re
import logging
import time
import uuid
from typing import Dict, List

from pr_pilot.github_client import GitHubClient
from pr_pilot.llm import parse_diff_hunks, analyze_diff
from pr_pilot.logging_config import set_request_id
from pr_pilot.review_summary import build_review_summary

logger = logging.getLogger(__name__)

_SEV_RE = re.compile(r'^\[([A-Z]+)\]')


def _save_review_run(
    owner: str, repo: str, pr_number: int, head_sha, files_reviewed: int,
    comments: List[dict], posted: bool,
) -> None:
    """Persist a review run and its comments to the database.

    Silently skips when DATABASE_URL is not configured.
    """
    if not os.getenv('DATABASE_URL'):
        return
    try:
        from pr_pilot.db import get_session, init_db
        from pr_pilot.models import ReviewRun, ReviewComment
        init_db()
        with get_session() as session:
            run = ReviewRun(
                owner=owner, repo=repo, pr_number=pr_number,
                head_sha=head_sha,
                files_reviewed=files_reviewed,
                comment_count=len(comments),
                posted=posted,
            )
            session.add(run)
            session.flush()
            for c in comments:
                m = _SEV_RE.match(c.get('body', ''))
                session.add(ReviewComment(
                    run_id=run.id,
                    path=c['path'],
                    position=c['position'],
                    severity=m.group(1) if m else None,
                    body=c.get('body'),
                ))
    except Exception:
        logger.exception('Failed to persist review run for %s/%s#%s', owner, repo, pr_number)


def process_pr_job(payload: Dict):
    """Process a PR: fetch diff, analyze, prepare comments, and optionally post.

    payload: { owner, repo, pr_number }
    """
    try:
        from rq import get_current_job
        job = get_current_job()
        job_id = job.id if job else str(uuid.uuid4())
    except Exception:
        job_id = str(uuid.uuid4())
    set_request_id(job_id)

    owner = payload.get("owner")
    repo = payload.get("repo")
    pr_number = payload.get("pr_number")
    if not (owner and repo and pr_number):
        logger.error("Invalid payload for process_pr_job: %s", payload)
        return {"error": "invalid payload"}

    _job_start = time.monotonic()

    token = os.getenv("GITHUB_TOKEN")
    gh = GitHubClient(token=token)
    diff = gh.fetch_pr_diff(owner, repo, pr_number)
    if not diff:
        logger.info("Empty diff for %s/%s#%s", owner, repo, pr_number)
        return {"comments": []}

    head_sha = getattr(gh, '_last_head_sha', None)

    # Load per-repo config from .reviewbot.yml (or defaults if absent)
    cfg = gh.fetch_reviewbot_config(owner, repo, head_sha) if head_sha else None
    if cfg is None:
        from pr_pilot.config import ReviewConfig
        cfg = ReviewConfig()

    if not cfg.enabled:
        logger.info('Review disabled via .reviewbot.yml for %s/%s#%s', owner, repo, pr_number)
        return {"comments": [], "skipped": "disabled"}

    files = parse_diff_hunks(diff)
    repo_id = f"{owner}/{repo}"
    _CONTEXT_LINES = int(os.getenv('LLM_CONTEXT_LINES', '20'))

    comments = []
    file_lines_cache: dict = {}
    files_reviewed = 0
    for file_path, hunks in files.items():
        if not cfg.should_review_file(file_path):
            logger.debug('Skipping %s (config filter)', file_path)
            continue
        files_reviewed += 1

        if head_sha and file_path not in file_lines_cache:
            file_lines_cache[file_path] = gh.fetch_file_content(owner, repo, file_path, head_sha)
        file_lines = file_lines_cache.get(file_path, [])

        for hunk in hunks:
            hunk_text = "\n".join(hunk['lines'])

            ctx_before: list = []
            ctx_after: list = []
            if file_lines:
                new_start_idx = hunk['new_start'] - 1  # 0-based
                new_end_idx = new_start_idx + hunk['new_lines']
                ctx_before = file_lines[max(0, new_start_idx - _CONTEXT_LINES):new_start_idx]
                ctx_after = file_lines[new_end_idx:new_end_idx + _CONTEXT_LINES]

            suggestions = analyze_diff(
                file_path, hunk_text, repo=repo_id,
                context_before=ctx_before or None,
                context_after=ctx_after or None,
                focus_instruction=cfg.focus_instruction(),
            )
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

    # Apply per-repo comment cap
    if len(comments) > cfg.max_comments:
        logger.info(
            'Capping comments from %d to %d for %s/%s#%s',
            len(comments), cfg.max_comments, owner, repo, pr_number,
        )
        comments = comments[:cfg.max_comments]

    summary = build_review_summary(comments, files_reviewed)

    posted = os.getenv('DO_POST') == '1' and bool(comments)
    _save_review_run(owner, repo, pr_number, head_sha, files_reviewed, comments, posted=posted)

    duration_ms = round((time.monotonic() - _job_start) * 1000, 1)

    if posted:
        review = gh.post_review(owner, repo, pr_number, comments, body=summary)
        review_id = getattr(review, 'id', None)
        logger.info(
            'review posted',
            extra={'owner': owner, 'repo': repo, 'pr_number': pr_number,
                   'duration_ms': duration_ms},
        )
        return {"posted": True, "review_id": review_id, "summary": summary}

    logger.info(
        'review complete',
        extra={'owner': owner, 'repo': repo, 'pr_number': pr_number,
               'duration_ms': duration_ms},
    )
    return {"posted": False, "comments": comments, "summary": summary}
