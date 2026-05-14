"""
db.py — PostgreSQL connection pool for JUGO.
Uses psycopg3 with a simple connection pool.
"""

import os
import psycopg
from psycopg.rows import dict_row


_pool = None


def _dsn() -> str:
    host = os.environ.get("DB_URL", "127.0.0.1")
    port = os.environ.get("DB_PORT", "5432") or "5432"
    name = os.environ.get("DB_NAME_JUGO", "jugo")
    user = os.environ.get("DB_USER_JUGO", "jugo")
    pw = os.environ.get("DB_PW_JUGO", "")
    return f"host={host} port={port} dbname={name} user={user} password={pw}"


def get_conn() -> psycopg.Connection:
    """Get a new connection (caller must close)."""
    return psycopg.connect(_dsn(), row_factory=dict_row)


def query(sql: str, params: tuple = ()) -> list[dict]:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()


def execute(sql: str, params: tuple = ()) -> None:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
        conn.commit()


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def is_configured() -> bool:
    return bool(os.environ.get("DB_PW_JUGO", "").strip())
