"""
core.py — JUGO business logic: tmux helpers + DeepL translation.
No FastAPI/HTTP dependencies. Returns plain dicts/strings.
"""

import os
import re
import shlex
import shutil

import libtmux

_PROFILE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")


def _get_server() -> libtmux.Server:
    return libtmux.Server()


def _find_pane(target: str) -> libtmux.Pane:
    """Resolve 'session:window.pane' target to a libtmux Pane."""
    session_name, rest = target.split(":", 1)
    window_idx, pane_idx = rest.split(".", 1)
    server = _get_server()
    for sess in server.sessions:
        if sess.name == session_name:
            for win in sess.windows:
                if win.window_index == window_idx:
                    for pane in win.panes:
                        if pane.pane_index == pane_idx:
                            return pane
    raise ValueError(f"Pane not found: {target}")


# ── tmux helpers ──────────────────────────────────────────────────────────────


def _parse_profile(raw_item: str) -> dict | None:
    parts = [part.strip() for part in raw_item.split("|", 2)]
    if not parts or not parts[0]:
        return None

    profile_id = parts[0].lower()
    if profile_id in {"shell", "new-shell"}:
        profile_id = "new-tmux"
    if not _PROFILE_RE.fullmatch(profile_id):
        return None

    label = parts[1] if len(parts) > 1 and parts[1] else profile_id.replace("-", " ")
    command = parts[2] if len(parts) > 2 else ""
    if "\n" in command or "\r" in command or "\x00" in command:
        return None

    return {"id": profile_id, "label": label, "command": command}


def _tmux_shell_allowed() -> bool:
    return os.environ.get("TMUX_SHELL", "").strip().lower() in {"1", "true", "yes", "on"}


def pane_profiles() -> list[dict]:
    """Return configured tmux session creation profiles."""
    raw = os.environ.get("JUGO_PANE_PROFILES", "")
    shell_allowed = _tmux_shell_allowed()
    profiles = []
    seen = set()
    for item in raw.split(","):
        profile = _parse_profile(item.strip())
        if not profile or profile["id"] in seen:
            continue
        if profile["id"] == "new-tmux" and not shell_allowed:
            continue
        profiles.append(profile)
        seen.add(profile["id"])
    return profiles


def _session_prefix() -> str | None:
    prefix = os.environ.get("JUGO_TMUX_SESSION_PREFIX", "").strip().lower()
    if _PROFILE_RE.fullmatch(prefix):
        return prefix
    return None


def list_panes() -> dict:
    """List all tmux panes as 'session:window.pane'."""
    try:
        server = _get_server()
        panes = []
        for sess in server.sessions:
            for win in sess.windows:
                for pane in win.panes:
                    target = f"{sess.name}:{win.window_index}.{pane.pane_index}"
                    info = f"{target} [{pane.pane_width}x{pane.pane_height}] {pane.pane_current_command}"
                    panes.append(info)
        return {"panes": panes}
    except Exception as e:
        return {"error": f"tmux error: {e}"}


def create_pane(user: str) -> dict:
    """Create a new tmux session for a configured profile."""
    profile = user.strip().lower()
    profiles = {item["id"]: item for item in pane_profiles()}
    if not profiles:
        return {"error": "Missing or invalid JUGO_PANE_PROFILES"}
    if profile not in profiles:
        return {"error": f"Invalid profile: {user}"}
    profile_data = profiles[profile]

    command = profile_data["command"].strip()
    if command:
        try:
            executable = shlex.split(command)[0]
        except ValueError as exc:
            return {"error": f"Invalid command for {profile_data['label']}: {exc}"}
        if not shutil.which(executable):
            return {"error": f"Command not found for {profile_data['label']}: {executable}"}

    try:
        server = _get_server()
        existing = [s.name for s in server.sessions]
    except Exception:
        existing = []

    n = 1
    prefix = _session_prefix()
    if not prefix:
        return {"error": "Missing or invalid JUGO_TMUX_SESSION_PREFIX"}
    session_base = f"{prefix}_{profile}"
    while f"{session_base}_{n}" in existing:
        n += 1
    session_name = f"{session_base}_{n}"

    try:
        server = _get_server()
        kwargs = {"session_name": session_name, "x": 200, "y": 50}
        if command:
            kwargs["window_command"] = command
        server.new_session(**kwargs)
    except Exception as e:
        return {"error": f"tmux error: {e}"}

    return {
        "ok": True,
        "session": session_name,
        "pane": f"{session_name}:0.0",
        "profile": profile,
        "label": profile_data["label"],
    }


def capture_pane(pane_target: str, lines: int = 100) -> dict:
    """Capture the last N lines from a tmux pane."""
    try:
        pane = _find_pane(pane_target)
        output = pane.capture_pane(start=-lines)
        return {"text": "\n".join(output)}
    except Exception as e:
        return {"error": f"tmux error: {e}"}


def send_keys(pane_target: str, text: str) -> dict:
    """Send text + Enter to a tmux pane."""
    text = text.rstrip("\n\r")
    try:
        pane = _find_pane(pane_target)
        pane.send_keys(text, enter=True, literal=True)
        return {"ok": True}
    except Exception as e:
        return {"error": f"tmux error: {e}"}


def send_special_key(pane_target: str, key: str) -> dict:
    """Send a special key (Up, Down, Enter, etc.) to a tmux pane."""
    try:
        pane = _find_pane(pane_target)
        pane.send_keys(key, enter=False)
        return {"ok": True}
    except Exception as e:
        return {"error": f"tmux error: {e}"}


# ── DeepL Key Rotation ───────────────────────────────────────────────────────

def _load_deepl_keys():
    keys = []
    val = os.environ.get("DEEPL_KEY", "")
    if val.strip():
        keys.append(val.strip())
    i = 2
    while True:
        val = os.environ.get(f"DEEPL_KEY_{i}", "")
        if not val.strip():
            break
        keys.append(val.strip())
        i += 1
    return keys

_deepl_keys = _load_deepl_keys()
_deepl_key_idx = 0

_FALLBACK_LANGUAGES = [
    {"code": "DE", "name": "German"},
    {"code": "EN", "name": "English"},
    {"code": "EN-US", "name": "English (American)"},
    {"code": "HR", "name": "Croatian"},
    {"code": "ES", "name": "Spanish"},
    {"code": "FR", "name": "French"},
    {"code": "IT", "name": "Italian"},
    {"code": "PT", "name": "Portuguese"},
    {"code": "PT-BR", "name": "Portuguese (Brazilian)"},
    {"code": "RU", "name": "Russian"},
    {"code": "TR", "name": "Turkish"},
    {"code": "PL", "name": "Polish"},
    {"code": "NL", "name": "Dutch"},
    {"code": "SV", "name": "Swedish"},
    {"code": "CS", "name": "Czech"},
    {"code": "SK", "name": "Slovak"},
    {"code": "SL", "name": "Slovenian"},
    {"code": "RO", "name": "Romanian"},
    {"code": "HU", "name": "Hungarian"},
    {"code": "UK", "name": "Ukrainian"},
    {"code": "BG", "name": "Bulgarian"},
    {"code": "ZH", "name": "Chinese"},
    {"code": "JA", "name": "Japanese"},
    {"code": "KO", "name": "Korean"},
]

def _next_key():
    global _deepl_key_idx
    if not _deepl_keys:
        return ""
    return _deepl_keys[_deepl_key_idx % len(_deepl_keys)]

def _rotate_key():
    global _deepl_key_idx
    _deepl_key_idx = (_deepl_key_idx + 1) % len(_deepl_keys)
    print(f"[DeepL] rotated to key #{_deepl_key_idx + 1}/{len(_deepl_keys)}")


def has_deepl_keys() -> bool:
    return bool(_deepl_keys)


def fallback_languages() -> dict:
    return {
        "source": _FALLBACK_LANGUAGES,
        "target": _FALLBACK_LANGUAGES,
    }


# ── DeepL Translation ─────────────────────────────────────────────────────────


async def get_usage() -> dict:
    import httpx
    if not _deepl_keys:
        return {"error": "No DEEPL_KEY set"}
    total_count, total_limit = 0, 0
    async with httpx.AsyncClient() as client:
        for key in _deepl_keys:
            resp = await client.get("https://api-free.deepl.com/v2/usage",
                headers={"Authorization": f"DeepL-Auth-Key {key}"})
            if resp.status_code == 200:
                d = resp.json()
                total_count += d["character_count"]
                total_limit += d["character_limit"]
    return {"character_count": total_count, "character_limit": total_limit}


async def translate_text(text, target_lang, source_lang=None, api_key=None,
                         api_url="https://api-free.deepl.com/v2/translate"):
    import httpx
    if not text.strip():
        return {"translation": ""}
    if not api_key and not _deepl_keys:
        return {"error": "No DEEPL_KEY set"}

    payload = {"text": [text], "target_lang": target_lang}
    if source_lang:
        payload["source_lang"] = source_lang

    tries = len(_deepl_keys) if not api_key else 1
    for _ in range(tries):
        key = api_key or _next_key()
        async with httpx.AsyncClient() as client:
            resp = await client.post(api_url,
                headers={"Authorization": f"DeepL-Auth-Key {key}"}, json=payload)
        if resp.status_code == 200:
            data = resp.json()
            return {
                "translation": data["translations"][0]["text"],
                "detected_source": data["translations"][0].get("detected_source_language", ""),
            }
        if resp.status_code in (429, 456) and not api_key:
            _rotate_key()
            continue
        if resp.status_code == 403:
            return {"error": "Invalid DeepL API key", "status": 403}
        return {"error": resp.text, "status": resp.status_code}
    return {"error": "All DeepL keys exhausted", "status": 456}


async def get_languages() -> dict:
    """Fetch supported languages from DeepL API."""
    import httpx

    key = os.environ.get("DEEPL_KEY", "")
    if not key:
        return fallback_languages()

    base = "https://api-free.deepl.com/v2/languages"
    headers = {"Authorization": f"DeepL-Auth-Key {key}"}

    async with httpx.AsyncClient() as client:
        src_r = await client.get(base, headers=headers, params={"type": "source"})
        tgt_r = await client.get(base, headers=headers, params={"type": "target"})

    if src_r.status_code != 200 or tgt_r.status_code != 200:
        return fallback_languages()

    return {
        "source": [{"code": l["language"], "name": l["name"]} for l in src_r.json()],
        "target": [{"code": l["language"], "name": l["name"]} for l in tgt_r.json()],
    }
