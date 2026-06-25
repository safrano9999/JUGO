"""db.py — SQLAlchemy database layer for JUGO."""

import os
import re
import time
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

_engine = None
_VALID_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_APP_TABLES = ("sessions", "users")
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _clean_identifier(value: str, *, field: str) -> str:
    clean = value.strip()
    if clean and not _VALID_IDENTIFIER.fullmatch(clean):
        raise ValueError(f"{field} must be empty or a valid SQL identifier")
    return clean


def _prefixed_table(base: str) -> str:
    prefix = _clean_identifier(os.environ.get("JUGO_DB_PREFIX", "jugo"), field="JUGO_DB_PREFIX")
    if not prefix:
        return base
    if base == prefix or base.startswith(f"{prefix}_"):
        return base
    return f"{prefix}_{base}"


def table_name(base: str) -> str:
    if base not in _APP_TABLES:
        raise ValueError(f"Unknown JUGO table: {base}")
    return _prefixed_table(base)


def _rewrite_sql(sql: str) -> str:
    rewritten = sql
    for base in _APP_TABLES:
        rewritten = re.sub(rf"\\b{base}\\b", table_name(base), rewritten)
    return rewritten


def _make_engine():
    db_type = os.environ.get("JUGO_DB_BACKEND", "sqlite").lower()
    if db_type == "sqlite":
        path = _PROJECT_ROOT / "sqlite.db"
        return create_engine(
            f"sqlite:///{path}",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    host = os.environ.get("JUGO_DB_HOST", "127.0.0.1")
    port = os.environ.get("JUGO_DB_PORT", "5432") or "5432"
    name = os.environ.get("JUGO_DB_NAME", "jugo")
    user = os.environ.get("JUGO_DB_USER", "jugo")
    pw = os.environ.get("JUGO_DB_PW", "")
    if db_type in {"postgres", "postgresql", "pgsql"}:
        return create_engine(f"postgresql+psycopg2://{user}:{pw}@{host}:{port}/{name}")
    if db_type in {"mysql", "mariadb"}:
        return create_engine(f"mysql+pymysql://{user}:{pw}@{host}:{port}/{name}?charset=utf8mb4")
    raise ValueError("JUGO_DB_BACKEND must be sqlite, postgres, postgresql, mysql, or mariadb")


def get_engine():
    global _engine
    if _engine is None:
        _engine = _make_engine()
        _init_tables(_engine)
    return _engine


def _init_tables(engine) -> None:
    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {table_name("sessions")} (
                id VARCHAR(64) PRIMARY KEY,
                pane TEXT,
                lines TEXT,
                last_hash VARCHAR(128),
                tts_position INTEGER DEFAULT 0,
                created_at FLOAT
            )
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS {table_name("users")} (
                name VARCHAR(255) PRIMARY KEY,
                password_hash TEXT,
                learned_words TEXT DEFAULT '[]',
                history TEXT DEFAULT '[]',
                updated_at FLOAT
            )
        """))


def query(sql: str, params: dict = {}) -> list[dict]:
    with get_engine().connect() as conn:
        result = conn.execute(text(_rewrite_sql(sql)), params)
        return [dict(row._mapping) for row in result]


def execute(sql: str, params: dict = {}) -> None:
    with get_engine().begin() as conn:
        conn.execute(text(_rewrite_sql(sql)), params)


def query_one(sql: str, params: dict = {}) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def is_configured() -> bool:
    try:
        get_engine()
        return True
    except Exception:
        return False
