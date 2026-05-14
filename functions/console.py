"""
console.py — In-memory operation log for JUGO.
Captures init + result of every LLM/translation/TTS operation.
Frontend polls GET /console?since=N to display entries.
"""

import time
from collections import deque

_entries: deque[dict] = deque(maxlen=500)
_counter = 0


def init(op: str, quadrant: str, detail: str) -> int:
    """Log operation start. Returns entry ID for matching result."""
    global _counter
    _counter += 1
    entry = {
        "id": _counter,
        "ts": time.time(),
        "op": op,
        "q": quadrant,
        "phase": "init",
        "detail": detail,
    }
    _entries.append(entry)
    return _counter


def result(entry_id: int, detail: str, error: str = "") -> None:
    """Log operation result, linked to init by ref_id."""
    global _counter
    _counter += 1
    entry = {
        "id": _counter,
        "ref": entry_id,
        "ts": time.time(),
        "phase": "result" if not error else "error",
        "detail": detail,
    }
    if error:
        entry["error"] = error
    _entries.append(entry)


def get(since: int = 0) -> list[dict]:
    """Return entries with id > since."""
    return [e for e in _entries if e["id"] > since or (e.get("phase") != "init" and e["id"] >= since)]


def get_all(since: int = 0) -> list[dict]:
    """Return all entries newer than since."""
    return [e for e in _entries if e["id"] > since]
