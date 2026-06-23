"""Tests for the RQ failure callback and dead-letter queue logic."""
import json
from unittest.mock import MagicMock, patch

from pr_pilot.retry import review_failure_callback, DEAD_LETTER_KEY


def _make_job(payload):
    job = MagicMock()
    job.id = 'test-job-id'
    job.args = [payload]
    return job


def test_failure_callback_pushes_to_dead_letter():
    job = _make_job({'owner': 'a', 'repo': 'b', 'pr_number': 1})
    connection = MagicMock()

    with patch.dict('os.environ', {'GITHUB_TOKEN': ''}):
        review_failure_callback(job, connection, Exception, ValueError('boom'), None)

    connection.lpush.assert_called_once()
    key, raw = connection.lpush.call_args[0]
    assert key == DEAD_LETTER_KEY
    data = json.loads(raw)
    assert data['job_id'] == 'test-job-id'
    assert 'boom' in data['error']
    assert 'failed_at' in data


def test_failure_callback_posts_comment_when_token_set():
    job = _make_job({'owner': 'myowner', 'repo': 'myrepo', 'pr_number': 42})
    connection = MagicMock()
    mock_gh = MagicMock()

    with patch.dict('os.environ', {'GITHUB_TOKEN': 'tok'}):
        with patch('pr_pilot.retry.GitHubClient', return_value=mock_gh):
            review_failure_callback(job, connection, Exception, ValueError('err'), None)

    args = mock_gh.post_issue_comment.call_args[0]
    assert args[:3] == ('myowner', 'myrepo', 42)
    assert isinstance(args[3], str) and len(args[3]) > 0


def test_failure_callback_no_comment_without_token():
    job = _make_job({'owner': 'a', 'repo': 'b', 'pr_number': 1})
    connection = MagicMock()

    with patch.dict('os.environ', {}, clear=True):
        with patch('pr_pilot.retry.GitHubClient') as mock_cls:
            review_failure_callback(job, connection, Exception, ValueError('err'), None)

    mock_cls.assert_not_called()


def test_failure_callback_no_comment_when_payload_incomplete():
    job = _make_job({})  # missing owner/repo/pr_number
    connection = MagicMock()

    with patch.dict('os.environ', {'GITHUB_TOKEN': 'tok'}):
        with patch('pr_pilot.retry.GitHubClient') as mock_cls:
            review_failure_callback(job, connection, Exception, ValueError('err'), None)

    mock_cls.assert_not_called()


def test_failure_callback_dead_letter_error_is_swallowed():
    job = _make_job({'owner': 'a', 'repo': 'b', 'pr_number': 1})
    connection = MagicMock()
    connection.lpush.side_effect = RuntimeError('redis down')

    with patch.dict('os.environ', {'GITHUB_TOKEN': ''}):
        # should not raise even if Redis lpush fails
        review_failure_callback(job, connection, Exception, ValueError('err'), None)
