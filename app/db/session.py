"""
Synchronous SQLAlchemy engine/session (see plan §"SQLAlchemy engine:
synchronous" decision) -- FastAPI route handlers that need DB access either
declare a plain `def` (FastAPI runs those in a threadpool automatically) or an
`async def` that calls DB work via starlette.concurrency.run_in_threadpool.
"""
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_settings = get_settings()

engine = create_engine(_settings.db_url, pool_pre_ping=True, pool_recycle=300, future=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
