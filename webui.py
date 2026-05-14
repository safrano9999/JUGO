#!/usr/bin/env python3
"""
codex-translate – A translation proxy for Codex CLI via tmux
Run: python3 webui.py
"""

import os
import sys
import json
from pathlib import Path
from dotenv import load_dotenv

_project_dir = Path(__file__).resolve().parent
sys.path.insert(0, str(_project_dir / "functions"))
load_dotenv(_project_dir / ".env", override=True)

from python_header import get  # noqa: F401

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

import core
import tts
import session
import chat
import console
from school_users import SchoolUserStore
import re
import time

def _require_env(key: str) -> str:
    value = get(key, "")
    if not value:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return value


def _require_port_env(key: str) -> int:
    value = _require_env(key)
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid integer for environment variable {key}: {value}") from exc
    if not (1 <= parsed <= 65535):
        raise RuntimeError(f"Invalid port for environment variable {key}: {value}")
    return parsed


def _require_bool_env(key: str) -> bool:
    value = _require_env(key).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"Invalid boolean for environment variable {key}: {value}")


SERVER_HOST = _require_env("HOST")
SERVER_PORT = _require_port_env("JUGO_PORT")
USE_TMUX = _require_bool_env("USE_TMUX")
SCHOOL_CONFIG_PATH = _project_dir / "school.json"
PROMPTS_CONFIG_PATH = _project_dir / "prompts.json"
STATIC_DIR = _project_dir / "static"
USERS_DIR = _project_dir / "users"
USER_STORE = SchoolUserStore(USERS_DIR)

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
    return SERVER_PORT


def _require_tmux() -> None:
    if not USE_TMUX:
        raise HTTPException(status_code=403, detail="tmux is disabled")


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost",
        "http://127.0.0.1",
        f"http://localhost:{SERVER_PORT}",
        f"http://127.0.0.1:{SERVER_PORT}",
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
    provider: str = "deepl"
    model: str | None = None
    ctx: str = ""


class SendKeysRequest(BaseModel):
    pane: str
    text: str
    ctx: str = ""


class CaptureRequest(BaseModel):
    pane: str
    lines: int = 100
    ctx: str = ""


class SendKeyRequest(BaseModel):
    pane: str
    key: str
    ctx: str = ""


class TTSRequest(BaseModel):
    text: str
    lang: str
    provider: str = "xai"
    voice: str | None = None
    model: str | None = None
    ctx: str = ""


# ── tmux endpoints ───────────────────────────────────────────────────────────


@app.get("/app/config")
def app_config():
    return {"useTmux": USE_TMUX}


@app.get("/panes")
def list_panes():
    if not USE_TMUX:
        return {"panes": []}
    result = core.list_panes()
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/panes/profiles")
def list_pane_profiles():
    if not USE_TMUX:
        return {"profiles": []}
    return {"profiles": core.pane_profiles()}


class CreatePaneRequest(BaseModel):
    user: str


@app.post("/panes/create")
def create_pane(req: CreatePaneRequest):
    _require_tmux()
    result = core.create_pane(req.user)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/capture")
def capture_pane(req: CaptureRequest):
    _require_tmux()
    _validate_pane(req.pane)
    ctx = req.ctx or "capture"
    cid = console.init("capture", ctx, f"{req.pane} ({req.lines} lines)")
    t0 = time.time()
    result = core.capture_pane(req.pane, req.lines)
    ms = int((time.time() - t0) * 1000)
    if "error" in result:
        console.result(cid, "", error=f"{result['error']} ({ms}ms)")
        raise HTTPException(status_code=400, detail=result["error"])
    text = result.get("text", "")
    console.result(cid, f"{len(text)} chars ({ms}ms)")
    return result


@app.post("/send")
def send_keys(req: SendKeysRequest):
    _require_tmux()
    _validate_pane(req.pane)
    ctx = req.ctx or "send"
    cid = console.init("send", ctx, f"{req.pane} \"{req.text[:40]}\"")
    t0 = time.time()
    result = core.send_keys(req.pane, req.text)
    ms = int((time.time() - t0) * 1000)
    if "error" in result:
        console.result(cid, "", error=f"{result['error']} ({ms}ms)")
        raise HTTPException(status_code=400, detail=result["error"])
    console.result(cid, f"ok ({ms}ms)")
    return result


@app.post("/sendkey")
def send_key(req: SendKeyRequest):
    _require_tmux()
    _validate_pane(req.pane)
    allowed = {"Up", "Down", "Enter", "Escape", "Left", "Right", "Tab", "BSpace"}
    if req.key not in allowed:
        raise HTTPException(status_code=422, detail=f"Key '{req.key}' not allowed")
    ctx = req.ctx or "sendkey"
    cid = console.init("sendkey", ctx, f"{req.pane} [{req.key}]")
    result = core.send_special_key(req.pane, req.key)
    if "error" in result:
        console.result(cid, "", error=result["error"])
        raise HTTPException(status_code=400, detail=result["error"])
    console.result(cid, "ok")
    return {"ok": True}


# ── Session endpoints ────────────────────────────────────────────────────────


class NewSessionRequest(BaseModel):
    pane: str = ""


@app.post("/session/new")
def session_new(req: NewSessionRequest):
    if req.pane:
        _require_tmux()
        _validate_pane(req.pane)
    return session.create(req.pane)


@app.get("/session/list")
def session_list():
    return {"sessions": session.list_all()}


@app.get("/session/{sid}")
def session_get(sid: str):
    s = session.get(sid)
    if not s:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"id": s["id"], "pane": s["pane"], "lines": s["lines"],
            "tts_position": s["tts_position"]}


@app.post("/session/{sid}/capture")
def session_capture(sid: str):
    cid = console.init("session-capture", "Q3", f"session {sid[:8]}")
    t0 = time.time()
    result = session.capture(sid)
    ms = int((time.time() - t0) * 1000)
    if "error" in result:
        console.result(cid, "", error=f"{result['error']} ({ms}ms)")
        raise HTTPException(status_code=400, detail=result["error"])
    console.result(cid, f"{result.get('new_lines', 0)} new lines ({ms}ms)")
    return result


@app.get("/session/{sid}/readable")
def session_readable(sid: str, from_pos: int | None = None):
    result = session.get_readable(sid, from_pos)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/session/{sid}/mark-read")
def session_mark_read(sid: str, position: int):
    session.mark_read(sid, position)
    return {"ok": True}


@app.delete("/session/{sid}")
def session_delete(sid: str):
    if not session.delete(sid):
        raise HTTPException(status_code=404, detail="Session not found")
    return {"ok": True}


@app.get("/session/{sid}/save")
def session_save(sid: str):
    result = session.save(sid)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/session/load")
def session_load(data: dict):
    return session.load(data)


# ── TTS endpoints ────────────────────────────────────────────────────────────


@app.get("/tts/providers")
def tts_providers():
    return {"providers": tts.available_providers()}


@app.get("/tts/discover/{provider}")
async def tts_discover(provider: str):
    result = await tts.discover(provider)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.post("/tts")
async def tts_synthesize(req: TTSRequest):
    ctx = req.ctx or "tts"
    voice_label = f" voice={req.voice}" if req.voice else ""
    cid = console.init("tts", ctx,
        f"{req.provider}{voice_label} [{req.lang}] \"{req.text[:40]}\"")
    t0 = time.time()
    result = await tts.synthesize(
        provider=req.provider, text=req.text, lang=req.lang,
        voice=req.voice, model=req.model,
    )
    ms = int((time.time() - t0) * 1000)
    if "error" in result:
        console.result(cid, "", error=f"{result['error']} ({ms}ms)")
        raise HTTPException(status_code=400, detail=result["error"])
    console.result(cid, f"audio {len(result['audio'])}B ({ms}ms)")
    return Response(content=result["audio"], media_type=result["content_type"])


@app.get("/tts/check/{provider}")
async def tts_check(provider: str):
    result = await tts.check(provider)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


# ── DeepL endpoint ───────────────────────────────────────────────────────────


@app.get("/usage")
async def usage():
    result = await core.get_usage()
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


@app.get("/languages")
async def languages():
    result = await core.get_languages()
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"{path.name} not found")
    return json.loads(path.read_text())


def _resolve_prompt(prompt_id: str) -> str:
    prompts = _load_json(PROMPTS_CONFIG_PATH)
    value = prompts
    for part in prompt_id.split("."):
        if not isinstance(value, dict) or part not in value:
            raise HTTPException(status_code=500, detail=f"Prompt not found: {prompt_id}")
        value = value[part]
    if not isinstance(value, str):
        raise HTTPException(status_code=500, detail=f"Prompt must be a string: {prompt_id}")
    return value


def _format_translation_prompt(template: str, text: str, source_lang: str | None, target_lang: str) -> str:
    source = source_lang or "auto-detected source language"
    return (
        template
        .replace("{source_lang}", source)
        .replace("{target_lang}", target_lang)
        .replace("{text}", text)
    )


@app.get("/translate/providers")
def translate_providers():
    providers = []
    if core.has_deepl_keys():
        providers.append({
            "id": "deepl",
            "name": "DeepL",
            "kind": "deepl",
            "models": [],
            "default_model": "",
        })
    for provider in chat.available_providers():
        item = dict(provider)
        item["kind"] = "llm"
        providers.append(item)
    return {"providers": providers}


@app.post("/translate")
async def translate(req: TranslateRequest):
    provider = (req.provider or "deepl").strip().lower()
    model_label = f"/{req.model}" if req.model else ""
    src = req.source_lang or "auto"
    ctx = req.ctx or "translate"
    provider_name = provider.upper() if provider == "deepl" else (chat.PROVIDERS.get(provider, {}).get("name", provider))
    cid = console.init("translate", ctx,
        f"{provider_name}{model_label} {src}→{req.target_lang} \"{req.text[:40]}\"")
    t0 = time.time()
    if provider == "deepl":
        result = await core.translate_text(
            text=req.text,
            target_lang=req.target_lang,
            source_lang=req.source_lang,
            api_key=req.api_key,
        )
    else:
        template = _resolve_prompt("translation.default")
        message = _format_translation_prompt(
            template=template,
            text=req.text,
            source_lang=req.source_lang,
            target_lang=req.target_lang,
        )
        result = await chat.chat(
            provider=provider,
            message=message,
            model=req.model,
            stateless=True,
            conversation_id="translation",
        )
        if "reply" in result:
            result = {
                "translation": result["reply"].strip(),
                "provider": provider,
                "model": result.get("model", req.model or ""),
            }
    ms = int((time.time() - t0) * 1000)
    if "error" in result:
        console.result(cid, "", error=f"{result['error']} ({ms}ms)")
        status = result.get("status", 400)
        raise HTTPException(status_code=status, detail=result["error"])
    console.result(cid, f"→ \"{result.get('translation','')[:50]}\" ({ms}ms)")
    return result


# ── Chat completion endpoints ────────────────────────────────────────────────


class ChatRequest(BaseModel):
    provider: str
    message: str
    model: str | None = None
    directives: list[str] | None = None
    lang: str | None = None
    stateless: bool = False
    conversation_id: str | None = None
    ctx: str = ""


@app.get("/chat/providers")
def chat_providers():
    return {"providers": chat.available_providers()}


@app.post("/chat/rediscover")
def chat_rediscover():
    cid = console.init("rediscover", "config", "LiteLLM model discovery")
    result = chat.discover_litellm()
    if "error" in result:
        console.result(cid, "", error=result["error"])
        return {"ok": False, "error": result["error"]}
    models = result.get("models", [])
    console.result(cid, f"{len(models)} models: {', '.join(models[:5])}")
    return {"ok": True, "models": models}


@app.post("/chat")
async def chat_completion(req: ChatRequest):
    model_label = f"/{req.model}" if req.model else ""
    ctx = req.ctx or "chat"
    provider_name = chat.PROVIDERS.get(req.provider, {}).get("name", req.provider)
    cid = console.init("chat", ctx,
        f"{provider_name}{model_label} \"{req.message[:40]}\"")
    t0 = time.time()
    result = await chat.chat(
        provider=req.provider,
        message=req.message,
        model=req.model,
        directives=req.directives,
        lang=req.lang,
        stateless=req.stateless,
        conversation_id=req.conversation_id,
    )
    ms = int((time.time() - t0) * 1000)
    if "error" in result:
        console.result(cid, "", error=f"{result['error']} ({ms}ms)")
        status = result.get("status", 400)
        raise HTTPException(status_code=status, detail=result["error"])
    console.result(cid, f"→ \"{result.get('reply','')[:50]}\" ({ms}ms)")
    return result


@app.post("/chat/{provider}/clear")
def chat_clear(provider: str):
    chat.clear_history(provider)
    return {"ok": True}


# ── School endpoint ─────────────────────────────────────────────────────────


@app.get("/school/config")
def school_config():
    config = _load_json(SCHOOL_CONFIG_PATH)

    presets = []
    for preset in config.get("presets", []):
        item = dict(preset)
        prompt_id = item.get("prompt_id") or f"school.{item.get('id', '')}"
        item["prompt_id"] = prompt_id
        item["prompt"] = _resolve_prompt(prompt_id)
        presets.append(item)

    config["presets"] = presets
    return config


# ── School users ───────────────────────────────────────────────────────────


def _normalize_username(name: str) -> str:
    try:
        return USER_STORE.normalize_name(name)
    except ValueError:
        raise HTTPException(status_code=400, detail="Username must be lowercase a-z only")


def _user_permission_error(exc: PermissionError) -> HTTPException:
    detail = str(exc)
    if detail == "invalid_password":
        return HTTPException(status_code=403, detail="Invalid password")
    if detail == "password_not_set":
        return HTTPException(status_code=403, detail="Password not set")
    if detail == "password_already_set":
        return HTTPException(status_code=409, detail="Password already set")
    return HTTPException(status_code=403, detail=detail or "Permission denied")


@app.get("/school/users")
def list_school_users():
    return {"users": USER_STORE.list_names()}


class CreateUserRequest(BaseModel):
    name: str
    password: str


@app.post("/school/users")
def create_school_user(req: CreateUserRequest):
    try:
        return USER_STORE.create(req.name, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileExistsError:
        raise HTTPException(status_code=409, detail="User already exists")


class UserPasswordRequest(BaseModel):
    password: str


@app.post("/school/users/{name}/load")
def get_school_user(name: str, req: UserPasswordRequest):
    try:
        return USER_STORE.load(name, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except PermissionError as exc:
        raise _user_permission_error(exc)


@app.post("/school/users/{name}/password")
def set_school_user_initial_password(name: str, req: UserPasswordRequest):
    try:
        return USER_STORE.set_initial_password(name, req.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except PermissionError as exc:
        raise _user_permission_error(exc)


@app.put("/school/users/{name}")
def update_school_user(name: str, data: dict):
    try:
        return USER_STORE.update(name, data.get("password", ""), data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="User not found")
    except PermissionError as exc:
        raise _user_permission_error(exc)


# ── Console / OpLog endpoint ────────────────────────────────────────────────


@app.get("/console")
def console_entries(since: int = 0):
    return {"entries": console.get_all(since)}


# ── Static frontend ─────────────────────────────────────────────────────────


if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def root():
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"status": "ok", "endpoints": ["/panes", "/capture", "/send", "/translate"]}


if __name__ == "__main__":
    uvicorn.run(app, host=SERVER_HOST, port=get_server_port())
