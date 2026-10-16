"""SQLite engine and session handling.

SQLite because this is a single-user local tool: one file, no server, trivial
to back up or delete. Measured at roughly 8 KB per job, so a few hundred jobs
is a couple of megabytes. Going through SQLAlchemy keeps a move to Postgres a
connection-string change rather than a rewrite.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app import config
from app.models import Base

_engine = None
_SessionFactory = None


def engine():
    global _engine
    if _engine is None:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _engine = create_engine(f"sqlite:///{config.DB_PATH}", future=True)
        Base.metadata.create_all(_engine)
    return _engine


@contextmanager
def session_scope() -> Iterator[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=engine(), future=True)

    session = _SessionFactory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_for_tests(path) -> None:
    """Point the module at a throwaway database."""
    global _engine, _SessionFactory
    config.DB_PATH = path
    _engine = None
    _SessionFactory = None
