"""db.py — SQLAlchemy database layer for JUGO. Supports SQLite and PostgreSQL."""

import os
import time
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

_engine = None


def _make_engine():
    db_type = os.environ.get("DB_TYPE", "sqlite").lower()
    if db_type == "sqlite":
        path = os.environ.get("DB_PATH", "jugo.db")
        return create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    host = os.environ.get("DB_URL", "127.0.0.1")
    port = os.environ.get("DB_PORT", "5432") or "5432"
    name = os.environ.get("DB_NAME_JUGO", "jugo")
    user = os.environ.get("DB_USER_JUGO", "jugo")
    pw = os.environ.get("DB_PW_JUGO", "")
    return create_engine(f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/{name}")


def get_engine():
    global _engine
    if _engine is None:
        _engine = _make_engine()
        _init_tables(_engine)
    return _engine


def _init_tables(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                pane TEXT,
                lines TEXT,
                last_hash TEXT,
                tts_position INTEGER DEFAULT 0,
                created_at REAL
            )
        """))
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                name TEXT PRIMARY KEY,
                password_hash TEXT,
                learned_words TEXT DEFAULT '[]',
                history TEXT DEFAULT '[]',
                updated_at REAL
            )
        """))


def query(sql: str, params: dict = {}) -> list[dict]:
    with get_engine().connect() as conn:
        result = conn.execute(text(sql), params)
        return [dict(row._mapping) for row in result]


def execute(sql: str, params: dict = {}) -> None:
    with get_engine().begin() as conn:
        conn.execute(text(sql), params)


def query_one(sql: str, params: dict = {}) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def is_configured() -> bool:
    try:
        get_engine()
        return True
    except Exception:
        return False
