#!/usr/bin/env python3
"""
codex-translate – A translation proxy for Codex CLI via tmux
Run: python3 server.py
"""

from python_header import get, get_port  # noqa: F401 — loads .env

import subprocess
import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os
import glob
from pathlib import Path

DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 840


def get_server_port() -> int:
    return get_port("JUGO_PORT", DEFAULT_PORT)


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DEEPL_API_URL = "https://api-free.deepl.com/v2/translate"  # free tier
# For Pro: https://api.deepl.com/v2/translate

TMUX = "/usr/bin/tmux"

def tmux_cmd(args: list) -> list:
    """Prepend tmux with explicit socket path."""
    uid = os.getuid()
    sockets = glob.glob(f"/tmp/tmux-{uid}/*")
    if sockets:
        return [TMUX, "-S", sockets[0]] + args
    return [TMUX] + args


# ── Models ────────────────────────────────────────────────────────────────────

class TranslateRequest(BaseModel):
    text: str
    source_lang: Optional[str] = None   # None = DeepL auto-detect
    target_lang: str
    api_key: Optional[str] = None

class SendKeysRequest(BaseModel):
    pane: str
    text: str

class CaptureRequest(BaseModel):
    pane: str
    lines: int = 100


# ── tmux helpers ──────────────────────────────────────────────────────────────

@app.get("/panes")
def list_panes():
    """List all tmux panes as 'session:window.pane'"""
    try:
        result = subprocess.run(
            tmux_cmd(["list-panes", "-a", "-F",
             "#{session_name}:#{window_index}.#{pane_index} [#{pane_width}x#{pane_height}] #{pane_current_command}"]),
            capture_output=True, text=True
        )
        panes = [line.strip() for line in result.stdout.strip().splitlines() if line.strip()]
        return {"panes": panes}
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="tmux not found")


@app.post("/capture")
def capture_pane(req: CaptureRequest):
    """Capture the last N lines from a tmux pane"""
    try:
        result = subprocess.run(
            tmux_cmd(["capture-pane", "-p", "-t", req.pane, "-S", f"-{req.lines}"]),
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail=f"tmux error: {result.stderr}")
        return {"text": result.stdout}
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="tmux not found")


@app.post("/send")
def send_keys(req: SendKeysRequest):
    """Send text + Enter to a tmux pane"""
    try:
        # Use set-buffer + paste-buffer to avoid newline-as-Enter issue
        subprocess.run(tmux_cmd(["set-buffer", req.text]), capture_output=True, text=True)
        result = subprocess.run(
            tmux_cmd(["paste-buffer", "-t", req.pane]),
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise HTTPException(status_code=400, detail=f"tmux error: {result.stderr}")
        subprocess.run(tmux_cmd(["send-keys", "-t", req.pane, "Enter"]), capture_output=True, text=True)
        return {"ok": True}
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="tmux not found")


# ── DeepL ─────────────────────────────────────────────────────────────────────

@app.post("/translate")
async def translate(req: TranslateRequest):
    if not req.text.strip():
        return {"translation": ""}

    api_key = req.api_key or os.environ.get("DEEPL_KEY", "")
    if not api_key:
        raise HTTPException(status_code=400, detail="Kein DeepL API Key – bitte in .env oder im Browser eintragen")

    payload = {
        "text": [req.text],
        "target_lang": req.target_lang,
    }
    if req.source_lang:
        payload["source_lang"] = req.source_lang

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            DEEPL_API_URL,
            headers={"Authorization": f"DeepL-Auth-Key {api_key}"},
            json=payload
        )

    if resp.status_code == 403:
        raise HTTPException(status_code=403, detail="Invalid DeepL API key")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)

    data = resp.json()
    translation = data["translations"][0]["text"]
    detected = data["translations"][0].get("detected_source_language", "")
    return {"translation": translation, "detected_source": detected}


# ── Static frontend ───────────────────────────────────────────────────────────

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    uvicorn.run("server:app", host=DEFAULT_HOST, port=get_server_port())
