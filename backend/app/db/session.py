"""
session.py
SQLite engine + session factory.

SQLite tolerates concurrent readers well but only one writer at a time.
At phase-1 scale (one PM, one designer, low volume) the simplest correct
thing is a single process-wide engine plus a lock that serializes every
session, rather than a connection pool — this trades a little request
latency under contention for never hitting a "database is locked" error.
Foreign key enforcement is off by default in SQLite, so it's turned on
per-connection below.
"""

import os
import sys
import threading
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from config import DB_PATH  # noqa: E402

# TKMIND_DB_PATH lets the test suite point at an isolated scratch database
# instead of the real app's data/tkmind.db — see TKMIND_DATA_DIR in
# ai/ingest/ingest.py for the matching FAISS-index isolation and why this
# matters (tests and real usage must never share mutable index/DB state).
_override = os.environ.get("TKMIND_DB_PATH")
_db_path = Path(_override).resolve() if _override else (_REPO_ROOT / DB_PATH).resolve()
_db_path.parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{_db_path}")


@event.listens_for(engine, "connect")
def _enable_foreign_keys(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

_write_lock = threading.Lock()


@contextmanager
def get_session():
    """Serialized session — every DB access (read or write) goes through this lock."""
    with _write_lock:
        session = SessionLocal()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def get_db():
    """FastAPI dependency wrapper around get_session()."""
    with get_session() as session:
        yield session
