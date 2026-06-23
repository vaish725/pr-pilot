import json
import logging
import os
from datetime import datetime, timezone

from pr_pilot.github_client import GitHubClient

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_INTERVALS = [60, 300, 900]  # seconds: 1 min, 5 min, 15 min
DEAD_LETTER_KEY = 'dead-letter:pr-jobs'

_UNAVAILABLE_COMMENT = (
    "> **PR Pilot** could not complete the automated review after multiple attempts.\n"
    "> The LLM service may be temporarily unavailable.\n"
    "> Push a new commit or re-open the PR to trigger another review attempt."
)


def review_failure_callback(job, connection, type, value, traceback):
    """RQ on_failure callback — push the failed job to a dead-letter list and post a PR comment."""
    payload = job.args[0] if job.args else {}
    owner = payload.get('owner')
    repo = payload.get('repo')
    pr_number = payload.get('pr_number')

    try:
        entry = json.dumps({
            'job_id': job.id,
            'payload': payload,
            'error': str(value),
            'failed_at': datetime.now(timezone.utc).isoformat(),
        })
        connection.lpush(DEAD_LETTER_KEY, entry)
        logger.error('Job %s dead-lettered after all retries: %s', job.id, value)
    except Exception:
        logger.exception('Failed to push job %s to dead-letter queue', job.id)

    if not (owner and repo and pr_number):
        return

    token = os.getenv('GITHUB_TOKEN')
    if not token:
        logger.warning('No GITHUB_TOKEN set; skipping degradation comment for %s/%s#%s', owner, repo, pr_number)
        return

    try:
        gh = GitHubClient(token=token)
        gh.post_issue_comment(owner, repo, pr_number, _UNAVAILABLE_COMMENT)
        logger.info('Posted degradation comment on %s/%s#%s', owner, repo, pr_number)
    except Exception:
        logger.exception('Failed to post degradation comment on %s/%s#%s', owner, repo, pr_number)
