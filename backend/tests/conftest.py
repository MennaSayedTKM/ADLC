import os
import sys
import tempfile
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_REPO_ROOT = _BACKEND_DIR.parent
for p in (_BACKEND_DIR, _REPO_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

# The test suite must never share the real app's data/ dir (SQLite file +
# FAISS index) — a test's mocked, fake-dimension embedding vectors and a
# developer's real embedding server both write to the same FAISS index file,
# and whichever wrote first permanently fixes its dimension for the other.
# This has happened in both directions. Point everything at an isolated
# scratch directory for the life of this test session instead. These env
# vars must be set before any test module (or app.db.session / ai.ingest.ingest)
# is imported, which conftest.py guarantees as the first thing pytest loads.
_TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="tkmind_test_data_"))
os.environ["TKMIND_DATA_DIR"] = str(_TEST_DATA_DIR)
os.environ["TKMIND_DB_PATH"] = str(_TEST_DATA_DIR / "test.db")

from app.db.base import Base  # noqa: E402
from app.db import models  # noqa: E402,F401  (registers tables on Base.metadata)
from app.db.session import engine  # noqa: E402

Base.metadata.create_all(engine)
