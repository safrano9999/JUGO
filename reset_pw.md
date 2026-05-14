# Password Hash Reset

Generate a fresh per-user `passwordHash` block:

```bash
python3 - <<'PY'
import base64, hashlib, json, os

password = "SECRETHERE"
salt = os.urandom(16)
iterations = 600_000
digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)

print(json.dumps({
    "algorithm": "pbkdf2_sha256",
    "iterations": iterations,
    "salt": base64.b64encode(salt).decode("ascii"),
    "hash": base64.b64encode(digest).decode("ascii"),
}, indent=2))
PY
```

Copy the output into the relevant user JSON as:

```json
"passwordHash": {
  "algorithm": "pbkdf2_sha256",
  "iterations": 600000,
  "salt": "...",
  "hash": "..."
}
```
