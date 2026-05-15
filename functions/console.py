"""
console.py — In-memory operation log for JUGO (session-scoped).
Each browser session only sees its own entries.
Frontend polls GET /console?since=N with X-Session-ID header.
Session ID is set via contextvars from middleware.
"""

import time
from collections import deque
from contextvars import ContextVar

# Current session ID — set by middleware before each request
current_session: ContextVar[str] = ContextVar("current_session", default="_global")

# Per-session entry storage
_sessions: dict[str, deque] = {}
_counters: dict[str, int] = {}

_MAX_ENTRIES = 500


def _get_session(sid: str) -> deque:
    if sid not in _sessions:
        _sessions[sid] = deque(maxlen=_MAX_ENTRIES)
        _counters[sid] = 0
    return _sessions[sid]


def init(op: str, quadrant: str, detail: str) -> int:
    """Log operation start. Returns entry ID for matching result."""
    sid = current_session.get()
    _get_session(sid)
    _counters[sid] += 1
    entry = {
        "id": _counters[sid],
        "ts": time.time(),
        "op": op,
        "q": quadrant,
        "phase": "init",
        "detail": detail,
    }
    _sessions[sid].append(entry)
    return _counters[sid]


def result(entry_id: int, detail: str, error: str = "") -> None:
    """Log operation result, linked to init by ref_id."""
    sid = current_session.get()
    _get_session(sid)
    _counters[sid] += 1
    entry = {
        "id": _counters[sid],
        "ref": entry_id,
        "ts": time.time(),
        "phase": "result" if not error else "error",
        "detail": detail,
    }
    if error:
        entry["error"] = error
    _sessions[sid].append(entry)


def get_all(since: int = 0) -> list[dict]:
    """Return all entries newer than since for the current session."""
    sid = current_session.get()
    if sid not in _sessions:
        return []
    return [e for e in _sessions[sid] if e["id"] > since]
