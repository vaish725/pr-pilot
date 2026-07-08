"""Tests for the admin/config API added alongside the dashboard:
/config, /runs/{id}/comments, /rerun, and /failed-jobs.
"""
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pr_pilot.models import Base, ReviewRun, ReviewComment
from pr_pilot.server import app

client = TestClient(app)


@pytest.fixture
def db(monkeypatch, tmp_path):
    """Point pr_pilot.db at a fresh sqlite file and wire up the module-level
    singletons the way tests/test_dashboard.py does, then tear down after.
    """
    db_url = f'sqlite:///{tmp_path}/test.db'
    monkeypatch.setenv('DATABASE_URL', db_url)

    eng = create_engine(db_url, connect_args={'check_same_thread': False}, future=True)
    Base.metadata.create_all(eng)

    import pr_pilot.db as db_module
    db_module._engine = eng
    db_module._SessionLocal = sessionmaker(bind=eng, expire_on_commit=False)
    db_module._initialized = True

    yield eng

    db_module._engine = None
    db_module._SessionLocal = None
    db_module._initialized = False


# ---------------------------------------------------------------------------
# /config
# ---------------------------------------------------------------------------

def test_get_config_no_db(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    resp = client.get('/config/acme/api')
    assert resp.status_code == 501


def test_get_config_defaults_when_no_row(db):
    resp = client.get('/config/acme/api')
    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        'owner': 'acme', 'repo': 'api', 'enabled': True, 'focus': 'all',
        'ignore_paths': [], 'max_comments': 20, 'updated_at': None,
    }


def test_put_config_creates_row_then_get_returns_it(db):
    body = {'enabled': False, 'focus': 'security', 'ignore_paths': ['*.md'], 'max_comments': 5}
    put_resp = client.put('/config/acme/api', json=body)
    assert put_resp.status_code == 200
    assert put_resp.json() == {'saved': True, 'owner': 'acme', 'repo': 'api'}

    get_resp = client.get('/config/acme/api')
    data = get_resp.json()
    assert data['enabled'] is False
    assert data['focus'] == 'security'
    assert data['ignore_paths'] == ['*.md']
    assert data['max_comments'] == 5
    assert data['updated_at'] is not None


def test_put_config_updates_existing_row(db):
    client.put('/config/acme/api', json={'enabled': True, 'focus': 'all', 'ignore_paths': [], 'max_comments': 20})
    client.put('/config/acme/api', json={'enabled': False, 'focus': 'style', 'ignore_paths': [], 'max_comments': 10})

    data = client.get('/config/acme/api').json()
    assert data['enabled'] is False
    assert data['focus'] == 'style'
    assert data['max_comments'] == 10


def test_put_config_invalid_focus_rejected(db):
    resp = client.put('/config/acme/api', json={'focus': 'not-a-real-mode'})
    assert resp.status_code == 422


@pytest.mark.parametrize('max_comments', [0, 101, -1])
def test_put_config_invalid_max_comments_rejected(db, max_comments):
    resp = client.put('/config/acme/api', json={'max_comments': max_comments})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# /runs/{run_id}/comments
# ---------------------------------------------------------------------------

def test_run_comments_no_db(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    resp = client.get('/runs/1/comments')
    assert resp.status_code == 501


def test_run_comments_not_found(db):
    resp = client.get('/runs/999/comments')
    assert resp.status_code == 404


def test_run_comments_returns_list(db):
    Session = sessionmaker(bind=db)
    with Session() as s:
        run = ReviewRun(owner='acme', repo='api', pr_number=1)
        s.add(run)
        s.flush()
        s.add(ReviewComment(run_id=run.id, path='a.py', position=3, severity='BUG', body='[BUG] oops'))
        s.add(ReviewComment(run_id=run.id, path='b.py', position=7, severity='STYLE', body='[STYLE] nit'))
        s.commit()
        run_id = run.id

    resp = client.get(f'/runs/{run_id}/comments')
    assert resp.status_code == 200
    data = resp.json()
    assert data['run_id'] == run_id
    assert len(data['comments']) == 2
    assert {c['path'] for c in data['comments']} == {'a.py', 'b.py'}


# ---------------------------------------------------------------------------
# /rerun
# ---------------------------------------------------------------------------

def test_rerun_without_rq_falls_back_to_thread(monkeypatch):
    monkeypatch.setattr('pr_pilot.server.RQ_AVAILABLE', False)
    with patch('pr_pilot.server.threading.Thread') as mock_thread:
        resp = client.post('/rerun/acme/api/5')
    assert resp.status_code == 200
    assert resp.json() == {'queued': True, 'job_id': None}
    mock_thread.assert_called_once()
    assert mock_thread.call_args.kwargs['target'].__name__ == '_bg'


def test_rerun_with_rq_enqueues_job(monkeypatch):
    monkeypatch.setattr('pr_pilot.server.RQ_AVAILABLE', True)
    mock_job = MagicMock(id='job-123')
    mock_queue = MagicMock()
    mock_queue.enqueue.return_value = mock_job

    with patch('pr_pilot.server.Redis') as mock_redis_cls, \
            patch('pr_pilot.server.Queue', return_value=mock_queue):
        mock_redis_cls.from_url.return_value = MagicMock()
        resp = client.post('/rerun/acme/api/5')

    assert resp.status_code == 200
    assert resp.json() == {'queued': True, 'job_id': 'job-123'}
    mock_queue.enqueue.assert_called_once()
    payload = mock_queue.enqueue.call_args[0][1]
    assert payload == {'owner': 'acme', 'repo': 'api', 'pr_number': 5}


def test_rerun_with_rq_failure_returns_500(monkeypatch):
    monkeypatch.setattr('pr_pilot.server.RQ_AVAILABLE', True)
    with patch('pr_pilot.server.Redis') as mock_redis_cls:
        mock_redis_cls.from_url.side_effect = RuntimeError('redis down')
        resp = client.post('/rerun/acme/api/5')
    assert resp.status_code == 500


# ---------------------------------------------------------------------------
# /failed-jobs
# ---------------------------------------------------------------------------

def test_failed_jobs_unavailable_without_rq(monkeypatch):
    monkeypatch.setattr('pr_pilot.server.RQ_AVAILABLE', False)
    resp = client.get('/failed-jobs')
    assert resp.status_code == 501


def test_failed_jobs_lists_jobs(monkeypatch):
    monkeypatch.setattr('pr_pilot.server.RQ_AVAILABLE', True)
    mock_job = MagicMock()
    mock_job.args = [{'owner': 'acme', 'repo': 'api', 'pr_number': 5}]
    mock_job.kwargs = {}
    mock_job.exc_info = 'Traceback...'
    mock_job.ended_at = None

    mock_registry = MagicMock()
    mock_registry.get_job_ids.return_value = ['job-1']

    with patch('pr_pilot.server.Redis') as mock_redis_cls, \
            patch('rq.registry.FailedJobRegistry', return_value=mock_registry), \
            patch('rq.job.Job.fetch', return_value=mock_job):
        mock_redis_cls.from_url.return_value = MagicMock()
        resp = client.get('/failed-jobs')

    assert resp.status_code == 200
    jobs = resp.json()['failed_jobs']
    assert len(jobs) == 1
    assert jobs[0]['id'] == 'job-1'
    assert jobs[0]['args'] == [{'owner': 'acme', 'repo': 'api', 'pr_number': 5}]


def test_failed_jobs_skips_jobs_that_fail_to_fetch(monkeypatch):
    monkeypatch.setattr('pr_pilot.server.RQ_AVAILABLE', True)
    mock_registry = MagicMock()
    mock_registry.get_job_ids.return_value = ['job-missing']

    with patch('pr_pilot.server.Redis') as mock_redis_cls, \
            patch('rq.registry.FailedJobRegistry', return_value=mock_registry), \
            patch('rq.job.Job.fetch', side_effect=RuntimeError('gone')):
        mock_redis_cls.from_url.return_value = MagicMock()
        resp = client.get('/failed-jobs')

    assert resp.status_code == 200
    assert resp.json()['failed_jobs'] == []


def test_failed_jobs_retry_unavailable_without_rq(monkeypatch):
    monkeypatch.setattr('pr_pilot.server.RQ_AVAILABLE', False)
    resp = client.post('/failed-jobs/job-1/retry')
    assert resp.status_code == 501


def test_failed_jobs_retry_reenqueues_and_removes(monkeypatch):
    monkeypatch.setattr('pr_pilot.server.RQ_AVAILABLE', True)
    mock_job = MagicMock()
    mock_job.args = [{'owner': 'acme', 'repo': 'api', 'pr_number': 5}]
    mock_queue = MagicMock()
    mock_remove = MagicMock()
    mock_registry_instance = MagicMock(remove=mock_remove)

    with patch('pr_pilot.server.Redis') as mock_redis_cls, \
            patch('pr_pilot.server.Queue', return_value=mock_queue), \
            patch('rq.job.Job.fetch', return_value=mock_job), \
            patch('rq.registry.FailedJobRegistry', return_value=mock_registry_instance):
        mock_redis_cls.from_url.return_value = MagicMock()
        resp = client.post('/failed-jobs/job-1/retry')

    assert resp.status_code == 200
    assert resp.json() == {'retried': True, 'job_id': 'job-1'}
    mock_queue.enqueue.assert_called_once()
    mock_remove.assert_called_once_with(mock_job)
