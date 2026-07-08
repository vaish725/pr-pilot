from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def _utcnow():
    return datetime.now(timezone.utc)


class ReviewRun(Base):
    __tablename__ = 'review_runs'

    id = Column(Integer, primary_key=True)
    owner = Column(String(255), nullable=False)
    repo = Column(String(255), nullable=False)
    pr_number = Column(Integer, nullable=False)
    head_sha = Column(String(40))
    files_reviewed = Column(Integer, default=0)
    comment_count = Column(Integer, default=0)
    posted = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    comments = relationship('ReviewComment', back_populates='run', cascade='all, delete-orphan')


class ReviewComment(Base):
    __tablename__ = 'review_comments'

    id = Column(Integer, primary_key=True)
    run_id = Column(Integer, ForeignKey('review_runs.id'), nullable=False)
    path = Column(String(1024), nullable=False)
    position = Column(Integer, nullable=False)
    severity = Column(String(20))
    body = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    run = relationship('ReviewRun', back_populates='comments')


class RepoConfig(Base):
    """Per-repo bot configuration stored in DB (overrides .reviewbot.yml)."""

    __tablename__ = 'repo_configs'

    id = Column(Integer, primary_key=True)
    owner = Column(String(255), nullable=False)
    repo = Column(String(255), nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    focus = Column(String(20), default='all', nullable=False)
    ignore_paths = Column(Text, default='[]')  # JSON array
    max_comments = Column(Integer, default=20, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint('owner', 'repo', name='uq_repo_config'),
    )


class CommentReaction(Base):
    """Tracks user reactions (+1/-1) posted as replies to bot review comments."""

    __tablename__ = 'comment_reactions'

    id = Column(Integer, primary_key=True)
    owner = Column(String(255), nullable=False)
    repo = Column(String(255), nullable=False)
    pr_number = Column(Integer, nullable=False)
    github_comment_id = Column(BigInteger, nullable=False)
    reaction = Column(String(10), nullable=False)  # '+1' or '-1'
    user_login = Column(String(255))
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint('github_comment_id', 'user_login', 'reaction', name='uq_comment_reaction'),
    )
