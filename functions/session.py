"""
session.py — Session management for continuous tmux capture.
Sessions accumulate output, track TTS read position, and filter readable sentences.
Uses PostgreSQL when configured, falls back to in-memory.
"""

import hashlib
import json
import re
import time
import uuid
from collections import Counter

import core


_sessions: dict[str, dict] = {}
_use_db = False

try:
    import db
    if db.is_configured():
        _use_db = True
except Exception:
    pass

# Patterns that indicate non-readable lines (code, shell, paths, etc.)
_SKIP_PATTERNS = [
    re.compile(r"^\s*$"),                          # empty
    re.compile(r"^\s*[\$\>\#\%]\s"),                # shell prompts
    re.compile(r"^\s*\>{3}\s"),                     # python REPL
    re.compile(r"^\s*\.\.\.\s*$"),                  # continuation
    re.compile(r"^\s*(import|from|def |class |if |elif |else:|for |while |return |raise |try:|except|finally|with |async |await )"),  # python
    re.compile(r"^\s*(const |let |var |function |=>|export |module\.)"),  # js
    re.compile(r"^\s*[\{\}\[\]\(\);]+\s*$"),        # brackets only
    re.compile(r"^[/\.\~][\w/\.\-]+"),              # file paths
    re.compile(r"^\s*(INFO|DEBUG|WARN|ERROR|WARNING)\s*:"),  # log lines
    re.compile(r"^\s*\d+\.\d+\.\d+"),               # version numbers / IPs
    re.compile(r"^\s*[\-=\*]{3,}\s*$"),              # separator lines
    re.compile(r"^\s*\|"),                           # table lines
    re.compile(r"^\s*(curl|wget|pip|npm|git|docker|podman|cd|ls|cat|mkdir|rm|cp|mv|chmod)\s"),  # commands
    re.compile(r"^\s*[A-Z_]{2,}="),                  # env vars
    re.compile(r"^[\s\W]*$"),                        # only whitespace/symbols
]

_MIN_WORDS = 3
_MIN_ALPHA_RATIO = 0.5


def is_readable(line: str) -> bool:
    """Check if a line looks like a natural language sentence."""
    stripped = line.strip()
    if len(stripped) < 10:
        return False
    for pat in _SKIP_PATTERNS:
        if pat.match(stripped):
            return False
    words = stripped.split()
    if len(words) < _MIN_WORDS:
        return False
    alpha_chars = sum(1 for c in stripped if c.isalpha())
    if len(stripped) > 0 and alpha_chars / len(stripped) < _MIN_ALPHA_RATIO:
        return False
    return True


def _save_to_db(session: dict) -> None:
    if not _use_db:
        return
    db.execute(
        """INSERT INTO sessions (id, pane, lines, last_hash, tts_position, created_at)
           VALUES (%s, %s, %s, %s, %s, to_timestamp(%s))
           ON CONFLICT (id) DO UPDATE SET
             lines = EXCLUDED.lines,
             last_hash = EXCLUDED.last_hash,
             tts_position = EXCLUDED.tts_position""",
        (session["id"], session["pane"], json.dumps(session["lines"]),
         session["last_hash"], session["tts_position"], session["created"]),
    )


def _load_from_db(sid: str) -> dict | None:
    if not _use_db:
        return None
    row = db.query_one("SELECT * FROM sessions WHERE id = %s", (sid,))
    if not row:
        return None
    lines = row["lines"] if isinstance(row["lines"], list) else json.loads(row["lines"]) if row["lines"] else []
    return {
        "id": row["id"],
        "pane": row["pane"],
        "lines": lines,
        "last_hash": row["last_hash"],
        "tts_position": row["tts_position"],
        "created": row["created_at"].timestamp() if row["created_at"] else time.time(),
    }


def create(pane: str = "") -> dict:
    """Create a new session, optionally bound to a tmux pane."""
    sid = str(uuid.uuid4())[:8]
    session = {
        "id": sid,
        "pane": pane,
        "lines": [],
        "last_hash": "",
        "tts_position": 0,
        "created": time.time(),
    }
    _sessions[sid] = session
    _save_to_db(session)
    return session


def get(sid: str) -> dict | None:
    s = _sessions.get(sid)
    if not s and _use_db:
        s = _load_from_db(sid)
        if s:
            _sessions[sid] = s
    return s


def list_all() -> list[dict]:
    if _use_db:
        rows = db.query("SELECT id, pane, lines, created_at FROM sessions ORDER BY created_at DESC")
        result = []
        for r in rows:
            lines = r["lines"] if isinstance(r["lines"], list) else json.loads(r["lines"]) if r["lines"] else []
            result.append({
                "id": r["id"], "pane": r["pane"], "lines_count": len(lines),
                "created": r["created_at"].timestamp() if r["created_at"] else 0,
            })
        return result
    return [{"id": s["id"], "pane": s["pane"], "lines_count": len(s["lines"]),
             "created": s["created"]} for s in _sessions.values()]


def delete(sid: str) -> bool:
    removed = _sessions.pop(sid, None) is not None
    if _use_db:
        db.execute("DELETE FROM sessions WHERE id = %s", (sid,))
        return True
    return removed


def capture(sid: str) -> dict:
    """Capture new lines from tmux pane, append delta to session."""
    session = get(sid)
    if not session:
        return {"error": f"Session {sid} not found"}

    result = core.capture_pane(session["pane"], 200)
    if "error" in result:
        return result

    current_lines = result["text"].rstrip("\n").split("\n")
    current_hash = hashlib.md5("\n".join(current_lines).encode()).hexdigest()

    if current_hash == session["last_hash"]:
        return {"changed": False, "total_lines": len(session["lines"])}

    existing = session["lines"]
    new_lines = _find_delta(existing, current_lines)

    if new_lines:
        existing.extend(new_lines)

    session["last_hash"] = current_hash
    _save_to_db(session)

    return {
        "changed": len(new_lines) > 0,
        "new_lines": new_lines,
        "total_lines": len(existing),
    }


def _find_delta(existing: list[str], current: list[str]) -> list[str]:
    """Find lines in current that are new compared to existing."""
    if not existing:
        return current

    max_overlap = min(50, len(existing), len(current))
    for overlap_size in range(max_overlap, 0, -1):
        tail = existing[-overlap_size:]
        for i in range(len(current) - overlap_size + 1):
            if current[i:i + overlap_size] == tail:
                return current[i + overlap_size:]

    recent_counts = Counter(existing[-500:])
    delta = []
    for line in current:
        if recent_counts[line] > 0:
            recent_counts[line] -= 1
        else:
            delta.append(line)
    return delta


def get_readable(sid: str, from_position: int | None = None) -> dict:
    """Get readable sentences from session, optionally from a position."""
    session = get(sid)
    if not session:
        return {"error": f"Session {sid} not found"}

    pos = from_position if from_position is not None else session["tts_position"]
    lines = session["lines"][pos:]
    readable = [line for line in lines if is_readable(line)]
    new_position = len(session["lines"])

    return {
        "text": "\n".join(readable),
        "from": pos,
        "to": new_position,
        "readable_count": len(readable),
        "total_count": len(lines),
    }


def mark_read(sid: str, position: int) -> None:
    """Update TTS read position."""
    session = get(sid)
    if session:
        session["tts_position"] = position
        _save_to_db(session)


def get_full_text(sid: str) -> str:
    """Get full session text."""
    session = get(sid)
    if not session:
        return ""
    return "\n".join(session["lines"])


def save(sid: str) -> dict:
    """Export session as JSON (for manual save)."""
    session = get(sid)
    if not session:
        return {"error": f"Session {sid} not found"}
    return {
        "id": session["id"],
        "pane": session["pane"],
        "lines": session["lines"],
        "tts_position": session["tts_position"],
        "created": session["created"],
    }


def load(data: dict) -> dict:
    """Import session from JSON (manual load)."""
    sid = data.get("id", str(uuid.uuid4())[:8])
    session = {
        "id": sid,
        "pane": data.get("pane", ""),
        "lines": data.get("lines", []),
        "last_hash": "",
        "tts_position": data.get("tts_position", 0),
        "created": data.get("created", time.time()),
    }
    _sessions[sid] = session
    _save_to_db(session)
    return session
