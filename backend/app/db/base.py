"""
base.py
Shared SQLAlchemy declarative base + a uuid() helper for primary keys.

Primary keys are String/UUID rather than autoincrement Integer — ids are
generated app-side before insert, which keeps document version-forking and
cross-table references simple without relying on DB-assigned identity values.
"""

import uuid

from sqlalchemy.orm import declarative_base

Base = declarative_base()


def new_uuid() -> str:
    return str(uuid.uuid4())
