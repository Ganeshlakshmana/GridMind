"""
db/session.py

Database engine setup and session factory for PostgreSQL relational layer.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.exc import OperationalError

from db.models import Base

# Load database URL from environment or fallback to local postgres
DB_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:password@localhost:5432/gridmind"
)

# pool_pre_ping checks the connection validity before querying
engine = create_engine(DB_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
db_session = scoped_session(SessionLocal)


_db_available_cache = None


def is_db_available() -> bool:
    """
    Check if the PostgreSQL database is online and reachable.
    Caches result to prevent repeated TCP timeouts when database is offline.
    """
    global _db_available_cache
    if _db_available_cache is not None:
        return _db_available_cache

    try:
        # Try to check connectivity
        with engine.connect() as conn:
            _db_available_cache = True
            return True
    except (OperationalError, Exception):
        _db_available_cache = False
        return False


def init_db() -> None:
    """
    Initialize all database tables defined in the models.
    """
    if is_db_available():
        Base.metadata.create_all(bind=engine)
