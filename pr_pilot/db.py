import logging
import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

logger = logging.getLogger(__name__)

_engine = None
_SessionLocal = None
_initialized = False


def get_engine():
    global _engine
    if _engine is None:
        url = os.getenv('DATABASE_URL', 'sqlite://')
        connect_args = {'check_same_thread': False} if url.startswith('sqlite') else {}
        _engine = create_engine(url, echo=False, future=True, connect_args=connect_args)
    return _engine


def init_db(engine=None):
    """Create all tables (idempotent — uses CREATE TABLE IF NOT EXISTS)."""
    global _initialized
    from pr_pilot.models import Base
    target = engine or get_engine()
    Base.metadata.create_all(target)
    _initialized = True


def _ensure_init():
    if not _initialized:
        init_db()


@contextmanager
def get_session(engine=None) -> Session:
    """Yield a session that auto-commits on success and rolls back on error."""
    global _SessionLocal
    _ensure_init()
    target = engine or get_engine()
    if _SessionLocal is None or engine is not None:
        factory = sessionmaker(bind=target, expire_on_commit=False)
    else:
        factory = _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = factory
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
