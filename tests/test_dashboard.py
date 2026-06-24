"""Tests for /reviews and /dashboard endpoints."""
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from pr_pilot.models import Base, ReviewRun
from pr_pilot.server import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# /reviews endpoint
# ---------------------------------------------------------------------------

def test_reviews_no_db(monkeypatch):
    monkeypatch.delenv('DATABASE_URL', raising=False)
    resp = client.get('/reviews/acme/api')
    assert resp.status_code == 501
    assert 'DATABASE_URL' in resp.json()['error']


def test_reviews_returns_list(monkeypatch, tmp_path):
    db_url = f'sqlite:///{tmp_path}/test.db'
    monkeypatch.setenv('DATABASE_URL', db_url)

    eng = create_engine(db_url, connect_args={'check_same_thread': False}, future=True)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    with Session() as s:
        s.add(ReviewRun(owner='acme', repo='api', pr_number=5,
                        head_sha='abc1234', files_reviewed=3, comment_count=2, posted=True))
        s.add(ReviewRun(owner='acme', repo='api', pr_number=6,
                        head_sha='def5678', files_reviewed=1, comment_count=0, posted=False))
        s.commit()

    import pr_pilot.db as db_module
    db_module._engine = eng
    db_module._SessionLocal = sessionmaker(bind=eng, expire_on_commit=False)
    db_module._initialized = True

    resp = client.get('/reviews/acme/api')
    assert resp.status_code == 200
    data = resp.json()
    assert data['owner'] == 'acme'
    assert data['repo'] == 'api'
    reviews = data['reviews']
    assert len(reviews) == 2
    pr_numbers = {r['pr_number'] for r in reviews}
    assert pr_numbers == {5, 6}

    db_module._engine = None
    db_module._SessionLocal = None
    db_module._initialized = False


def test_reviews_limit_parameter(monkeypatch, tmp_path):
    db_url = f'sqlite:///{tmp_path}/test_limit.db'
    monkeypatch.setenv('DATABASE_URL', db_url)

    eng = create_engine(db_url, connect_args={'check_same_thread': False}, future=True)
    Base.metadata.create_all(eng)
    Session = sessionmaker(bind=eng)
    with Session() as s:
        for i in range(5):
            s.add(ReviewRun(owner='x', repo='y', pr_number=i + 1))
        s.commit()

    import pr_pilot.db as db_module
    db_module._engine = eng
    db_module._SessionLocal = sessionmaker(bind=eng, expire_on_commit=False)
    db_module._initialized = True

    resp = client.get('/reviews/x/y?limit=2')
    assert resp.status_code == 200
    assert len(resp.json()['reviews']) == 2

    db_module._engine = None
    db_module._SessionLocal = None
    db_module._initialized = False


def test_reviews_wrong_repo_returns_empty(monkeypatch, tmp_path):
    db_url = f'sqlite:///{tmp_path}/test_empty.db'
    monkeypatch.setenv('DATABASE_URL', db_url)

    eng = create_engine(db_url, connect_args={'check_same_thread': False}, future=True)
    Base.metadata.create_all(eng)

    import pr_pilot.db as db_module
    db_module._engine = eng
    db_module._SessionLocal = sessionmaker(bind=eng, expire_on_commit=False)
    db_module._initialized = True

    resp = client.get('/reviews/nobody/nothing')
    assert resp.status_code == 200
    assert resp.json()['reviews'] == []

    db_module._engine = None
    db_module._SessionLocal = None
    db_module._initialized = False


# ---------------------------------------------------------------------------
# /dashboard endpoint
# ---------------------------------------------------------------------------

def test_dashboard_returns_html():
    resp = client.get('/dashboard')
    assert resp.status_code == 200
    assert 'text/html' in resp.headers['content-type']
    assert 'PR Pilot Admin' in resp.text
    assert 'react' in resp.text.lower()
