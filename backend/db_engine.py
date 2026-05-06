"""
Database engine factory with connection pooling.
SQLAlchemy core (not ORM) — keeps existing SQL, adds pooling.
"""
import os
import sqlite3
from contextlib import contextmanager
from sqlalchemy import create_engine, event
from sqlalchemy.pool import QueuePool


DEFAULT_POOL_SIZE = int(os.getenv("DB_POOL_SIZE", "10"))
DEFAULT_MAX_OVERFLOW = int(os.getenv("DB_MAX_OVERFLOW", "20"))


def create_pooled_engine(db_path: str = "data/debate_system.db", db_url: str = ""):
    """Create a SQLAlchemy engine with connection pooling.

    Pool size is configurable via DB_POOL_SIZE and DB_MAX_OVERFLOW env vars.
    """
    if db_url.startswith("postgresql://"):
        engine = create_engine(
            db_url,
            pool_size=DEFAULT_POOL_SIZE,
            max_overflow=DEFAULT_MAX_OVERFLOW,
            pool_pre_ping=True,
            echo=False,
        )
    else:
        resolved_url = (
            db_url if db_url.startswith("sqlite:///") else f"sqlite:///{db_path}"
        )
        engine = create_engine(
            resolved_url,
            poolclass=QueuePool,
            pool_size=DEFAULT_POOL_SIZE,
            max_overflow=DEFAULT_MAX_OVERFLOW,
            pool_pre_ping=True,
            echo=False,
            connect_args={"check_same_thread": False},
        )

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):
            if isinstance(dbapi_conn, sqlite3.Connection):
                dbapi_conn.row_factory = sqlite3.Row

    return engine


@contextmanager
def transaction(engine):
    """Context manager for multi-statement transactions with automatic rollback on error."""
    conn = engine.raw_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
