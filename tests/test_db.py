"""Tests for PostgreSQL storage layer using SQLite in-memory."""
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker

from pr_pilot.models import Base, ReviewRun, ReviewComment, CommentReaction


@pytest.fixture
def engine():
    eng = create_engine('sqlite://', connect_args={'check_same_thread': False}, future=True)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)


@pytest.fixture
def session(engine):
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    s = factory()
    yield s
    s.rollback()
    s.close()


def test_review_run_persisted(session):
    run = ReviewRun(owner='acme', repo='api', pr_number=7, files_reviewed=3, comment_count=5, posted=True)
    session.add(run)
    session.commit()

    fetched = session.scalar(select(ReviewRun).where(ReviewRun.pr_number == 7))
    assert fetched.owner == 'acme'
    assert fetched.files_reviewed == 3
    assert fetched.posted is True
    assert fetched.created_at is not None


def test_review_comments_cascade_from_run(session):
    run = ReviewRun(owner='a', repo='b', pr_number=1)
    session.add(run)
    session.flush()

    session.add(ReviewComment(run_id=run.id, path='foo.py', position=3, severity='BUG', body='[BUG] oops'))
    session.add(ReviewComment(run_id=run.id, path='bar.py', position=5, severity='STYLE', body='[STYLE] nit'))
    session.commit()

    count = session.scalar(select(func.count()).select_from(ReviewComment).where(ReviewComment.run_id == run.id))
    assert count == 2


def test_cascade_delete_removes_comments(session):
    run = ReviewRun(owner='a', repo='b', pr_number=2)
    session.add(run)
    session.flush()
    session.add(ReviewComment(run_id=run.id, path='x.py', position=1))
    session.commit()

    session.delete(run)
    session.commit()

    remaining = session.scalar(select(func.count()).select_from(ReviewComment))
    assert remaining == 0


def test_comment_reaction_unique_constraint(session):
    from sqlalchemy.exc import IntegrityError
    session.add(CommentReaction(owner='a', repo='b', pr_number=1, github_comment_id=100, reaction='+1', user_login='alice'))
    session.commit()

    session.add(CommentReaction(owner='a', repo='b', pr_number=1, github_comment_id=100, reaction='+1', user_login='alice'))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_reaction_positive_and_negative_stored(session):
    session.add(CommentReaction(owner='o', repo='r', pr_number=3, github_comment_id=200, reaction='+1', user_login='alice'))
    session.add(CommentReaction(owner='o', repo='r', pr_number=3, github_comment_id=201, reaction='-1', user_login='bob'))
    session.commit()

    rows = session.execute(
        select(CommentReaction.reaction, func.count()).group_by(CommentReaction.reaction)
    ).all()
    counts = {r: c for r, c in rows}
    assert counts['+1'] == 1
    assert counts['-1'] == 1


def test_severity_breakdown_query(session):
    run = ReviewRun(owner='x', repo='y', pr_number=10)
    session.add(run)
    session.flush()

    for sev in ['BUG', 'BUG', 'SECURITY', 'STYLE']:
        session.add(ReviewComment(run_id=run.id, path='f.py', position=1, severity=sev))
    session.commit()

    rows = session.execute(
        select(ReviewComment.severity, func.count())
        .join(ReviewRun)
        .where(ReviewRun.owner == 'x', ReviewRun.repo == 'y')
        .group_by(ReviewComment.severity)
    ).all()
    breakdown = {sev: cnt for sev, cnt in rows}
    assert breakdown['BUG'] == 2
    assert breakdown['SECURITY'] == 1
    assert breakdown['STYLE'] == 1
