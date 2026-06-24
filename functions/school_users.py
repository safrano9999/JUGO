"""
school_users.py — User store with password hashes.
Uses PostgreSQL when configured (JUGO_DB_PW set), falls back to JSON files.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import time
from pathlib import Path


class SchoolUserStore:
    _USER_RE = re.compile(r"^[a-z]+$")
    _ALGORITHM = "pbkdf2_sha256"
    _ITERATIONS = 600_000

    def __init__(self, users_dir: Path):
        self.users_dir = users_dir
        self.users_dir.mkdir(exist_ok=True)
        self._use_db = False
        try:
            import db
            if db.is_configured():
                self._use_db = True
                self._migrate_json_to_db()
        except Exception:
            pass

    def _migrate_json_to_db(self) -> None:
        """One-time migration: copy JSON users into DB if they don't exist there yet."""
        import db
        for path in self.users_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                name = data.get("name", path.stem)
                existing = db.query_one("SELECT name FROM users WHERE name = :name", {"name": name})
                if not existing:
                    db.execute(
                        "INSERT INTO users (name, password_hash, learned_words, history) VALUES (:name, :pw, :lw, :hist)",
                        {"name": name, "pw": json.dumps(data.get("passwordHash", {})),
                         "lw": json.dumps(data.get("learnedWords", [])),
                         "hist": json.dumps(data.get("history", []))},
                    )
            except Exception:
                pass

    def normalize_name(self, name: str) -> str:
        clean = name.strip().lower()
        if not self._USER_RE.fullmatch(clean):
            raise ValueError("Username must be lowercase a-z only")
        return clean

    def list_names(self) -> list[str]:
        if self._use_db:
            import db
            rows = db.query("SELECT name FROM users ORDER BY name", {})
            return [r["name"] for r in rows]
        return sorted(p.stem for p in self.users_dir.glob("*.json"))

    def create(self, name: str, password: str) -> dict:
        clean = self.normalize_name(name)
        if not password:
            raise ValueError("Password required")
        pw_hash = self.hash_password(password)
        if self._use_db:
            import db
            existing = db.query_one("SELECT name FROM users WHERE name = :name", {"name": clean})
            if existing:
                raise FileExistsError(clean)
            db.execute(
                "INSERT INTO users (name, password_hash, learned_words, history) VALUES (:name, :pw, '[]', '[]')",
                {"name": clean, "pw": json.dumps(pw_hash)},
            )
        else:
            path = self._path(clean)
            if path.exists():
                raise FileExistsError(clean)
            self._write(path, {"name": clean, "passwordHash": pw_hash, "learnedWords": [], "history": []})
        return self._public({"name": clean, "passwordHash": pw_hash, "learnedWords": [], "history": []})

    def load(self, name: str, password: str) -> dict:
        data = self._read_existing(name)
        self._require_password(data, password)
        return self._public(data)

    def set_initial_password(self, name: str, password: str) -> dict:
        clean = self.normalize_name(name)
        if not password:
            raise ValueError("Password required")
        data = self._read_existing(clean)
        if data.get("passwordHash"):
            raise PermissionError("password_already_set")
        pw_hash = self.hash_password(password)
        if self._use_db:
            import db
            db.execute(
                "UPDATE users SET password_hash = :pw, updated_at = :ts WHERE name = :name",
                {"pw": json.dumps(pw_hash), "ts": time.time(), "name": clean},
            )
        else:
            path = self._path(clean)
            data["passwordHash"] = pw_hash
            data.setdefault("learnedWords", [])
            data.setdefault("history", [])
            self._write(path, data)
        data["passwordHash"] = pw_hash
        return self._public(data)

    def update(self, name: str, password: str, user_data: dict) -> dict:
        clean = self.normalize_name(name)
        existing = self._read_existing(clean)
        self._require_password(existing, password)
        learned = user_data.get("learnedWords", [])
        history = user_data.get("history", [])
        if self._use_db:
            import db
            db.execute(
                "UPDATE users SET learned_words = :lw, history = :hist, updated_at = :ts WHERE name = :name",
                {"lw": json.dumps(learned), "hist": json.dumps(history), "ts": time.time(), "name": clean},
            )
        else:
            data = {
                "name": clean,
                "passwordHash": existing["passwordHash"],
                "learnedWords": learned,
                "history": history,
            }
            self._write(self._path(clean), data)
        return {"ok": True}

    def _read_existing(self, name: str) -> dict:
        clean = self.normalize_name(name)
        if self._use_db:
            import db
            row = db.query_one("SELECT * FROM users WHERE name = :name", {"name": clean})
            if not row:
                raise FileNotFoundError(clean)
            return {
                "name": row["name"],
                "passwordHash": row["password_hash"] if isinstance(row["password_hash"], dict) else json.loads(row["password_hash"]) if row["password_hash"] else {},
                "learnedWords": row["learned_words"] if isinstance(row["learned_words"], list) else json.loads(row["learned_words"]) if row["learned_words"] else [],
                "history": row["history"] if isinstance(row["history"], list) else json.loads(row["history"]) if row["history"] else [],
            }
        return self._read_path(self._path(clean))

    def _path(self, name: str) -> Path:
        return self.users_dir / f"{name}.json"

    def _read_path(self, path: Path) -> dict:
        if not path.exists():
            raise FileNotFoundError(path)
        return json.loads(path.read_text())

    def _write(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    def _public(self, data: dict) -> dict:
        return {
            "name": data.get("name", ""),
            "learnedWords": data.get("learnedWords", []),
            "history": data.get("history", []),
            "hasPassword": bool(data.get("passwordHash")),
        }

    def _require_password(self, data: dict, password: str) -> None:
        password_hash = data.get("passwordHash")
        if not password_hash:
            raise PermissionError("password_not_set")
        if not self.verify_password(password, password_hash):
            raise PermissionError("invalid_password")

    @classmethod
    def hash_password(cls, password: str) -> dict:
        salt = os.urandom(16)
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, cls._ITERATIONS
        )
        return {
            "algorithm": cls._ALGORITHM,
            "iterations": cls._ITERATIONS,
            "salt": base64.b64encode(salt).decode("ascii"),
            "hash": base64.b64encode(digest).decode("ascii"),
        }

    @classmethod
    def verify_password(cls, password: str, password_hash: dict) -> bool:
        if password_hash.get("algorithm") != cls._ALGORITHM:
            return False
        try:
            iterations = int(password_hash["iterations"])
            salt = base64.b64decode(password_hash["salt"])
            expected = base64.b64decode(password_hash["hash"])
        except (KeyError, ValueError, TypeError):
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        )
        return hmac.compare_digest(digest, expected)
