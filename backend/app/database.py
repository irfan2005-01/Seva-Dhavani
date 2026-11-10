"""SQLAlchemy engine and session setup."""

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


def _database_url() -> str:
    configured = os.getenv("DATABASE_URL")
    if configured:
        return configured
    # Keep the default database beside the backend so launch location is irrelevant.
    db_path = Path(__file__).resolve().parents[1] / "seva_dhwani.db"
    return f"sqlite:///{db_path.as_posix()}"


DATABASE_URL = _database_url()
connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
