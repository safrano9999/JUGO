"""
core.py — JUGO (codex-translate) business logic.
No FastAPI/HTTP dependencies. Returns plain dicts/strings.
"""

import glob
import os
import subprocess
from pathlib import Path

TMUX = "/usr/bin/tmux"


# ── tmux helpers ──────────────────────────────────────────────────────────────


def _tmux_socket_args() -> list[str]:
    """Return [-S, <socket>] if a tmux socket exists, else []."""
    uid = os.getuid()
    sockets = glob.glob(f"/tmp/tmux-{uid}/*")
    if sockets:
        return ["-S", sockets[0]]
    return []


def tmux_cmd(args: list[str]) -> list[str]:
    """Prepend tmux with explicit socket path."""
    return [TMUX] + _tmux_socket_args() + args


def list_panes() -> dict:
    """List all tmux panes as 'session:window.pane'."""
    result = subprocess.run(
        tmux_cmd([
            "list-panes", "-a", "-F",
            "#{session_name}:#{window_index}.#{pane_index} "
            "[#{pane_width}x#{pane_height}] #{pane_current_command}",
        ]),
        capture_output=True, text=True, check=False,
    )
    panes = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
    return {"panes": panes}


def capture_pane(pane: str, lines: int = 100) -> dict:
    """Capture the last N lines from a tmux pane."""
    result = subprocess.run(
        tmux_cmd(["capture-pane", "-p", "-t", pane, "-S", f"-{lines}"]),
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return {"error": f"tmux error: {result.stderr}"}
    return {"text": result.stdout}


def send_keys(pane: str, text: str) -> dict:
    """Send text + Enter to a tmux pane."""
    subprocess.run(tmux_cmd(["set-buffer", text]), capture_output=True, text=True, check=False)
    result = subprocess.run(
        tmux_cmd(["paste-buffer", "-t", pane]),
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return {"error": f"tmux error: {result.stderr}"}
    subprocess.run(
        tmux_cmd(["send-keys", "-t", pane, "Enter"]),
        capture_output=True, text=True, check=False,
    )
    return {"ok": True}


# ── DeepL Translation ─────────────────────────────────────────────────────────


async def translate_text(
    text: str,
    target_lang: str,
    source_lang: str | None = None,
    api_key: str | None = None,
    api_url: str = "https://api-free.deepl.com/v2/translate",
) -> dict:
    """Translate text via DeepL API. Returns dict with translation + detected source."""
    import httpx

    if not text.strip():
        return {"translation": ""}

    key = api_key or os.environ.get("DEEPL_KEY", "")
    if not key:
        return {"error": "Kein DeepL API Key – bitte DEEPL_KEY in .env setzen"}

    payload = {"text": [text], "target_lang": target_lang}
    if source_lang:
        payload["source_lang"] = source_lang

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            api_url,
            headers={"Authorization": f"DeepL-Auth-Key {key}"},
            json=payload,
        )

    if resp.status_code == 403:
        return {"error": "Invalid DeepL API key", "status": 403}
    if resp.status_code != 200:
        return {"error": resp.text, "status": resp.status_code}

    data = resp.json()
    return {
        "translation": data["translations"][0]["text"],
        "detected_source": data["translations"][0].get("detected_source_language", ""),
    }
