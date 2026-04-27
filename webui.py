#!/usr/bin/env python3
"""
codex-translate – A translation proxy for Codex CLI via tmux
Run: python3 webui.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "functions"))

from python_header import get, get_port  # noqa: F401 — loads .env

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import core
import re

DEFAULT_HOST = "0.0.0.0"

DEFAULT_PORT = 840

# Tmux pane targets: "session:window.pane", e.g. "main:0.1" or "0:1.2"
_PANE_RE = re.compile(r"^[\w\-]+:\d+\.\d+$")


def _validate_pane(pane: str) -> None:
    """Raise 422 if the pane target doesn't match the expected tmux format."""
    if not _PANE_RE.match(pane):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid pane target '{pane}'. Expected format: session:window.pane (e.g. 'main:0.1')",
        )


def get_server_port() -> int:
    return get_port("JUGO_PORT", DEFAULT_PORT)


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://127.0.0.1",
        f"http://localhost:{DEFAULT_PORT}",
        f"http://127.0.0.1:{DEFAULT_PORT}",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Models ────────────────────────────────────────────────────────────────────


class TranslateRequest(BaseModel):
    text: str
    source_lang: str | None = None
    target_lang: str
    api_key: str | None = None


class SendKeysRequest(BaseModel):
    pane: str
    text: str


class CaptureRequest(BaseModel):
    pane: str
    lines: int = 100


# ── tmux endpoints ───────────────────────────────────────────────────────────


@app.get("/panes")
def list_panes():
    result = core.list_panes()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.post("/capture")
def capture_pane(req: CaptureRequest):
    _validate_pane(req.pane)
    result = core.capture_pane(req.pane, req.lines)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/send")
def send_keys(req: SendKeysRequest):
    _validate_pane(req.pane)
    result = core.send_keys(req.pane, req.text)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── DeepL endpoint ───────────────────────────────────────────────────────────


@app.post("/translate")
async def translate(req: TranslateRequest):
    result = await core.translate_text(
        text=req.text,
        target_lang=req.target_lang,
        source_lang=req.source_lang,
        api_key=req.api_key,
    )
    if "error" in result:
        status = result.get("status", 400)
        raise HTTPException(status_code=status, detail=result["error"])
    return result


# ── Static frontend ─────────────────────────────────────────────────────────


app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def root():
    return FileResponse("static/index.html")


if __name__ == "__main__":
    uvicorn.run(app, host=DEFAULT_HOST, port=get_server_port())
