"""
chat.py — LLM chat completion for multiple providers (OpenAI, Gemini, Grok/xAI).
Returns plain dicts, no HTTP dependencies.
"""

import os
import asyncio
import httpx
from console import current_session


# Provider configs: endpoint, env key, default model
PROVIDERS = {
    "xai": {
        "name": "xAI",
        "env_key": "XAI_API_KEY",
        "base_url": "https://api.x.ai/v1/chat/completions",
        "default_model": "grok-4.3",
        "models": ["grok-4-fast-non-reasoning", "grok-4.3", "grok-3-mini", "grok-3"],
    },
    "google": {
        "name": "Google",
        "env_key": "GEMINI_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "default_model": "gemini-3.1-flash-lite",
        "models": ["gemini-3.1-flash-lite", "gemini-2.5-flash", "gemini-2.5-pro"],
    },
    "openai": {
        "name": "OpenAI",
        "env_key": "OPENAI_KEY",
        "base_url": "https://api.openai.com/v1/chat/completions",
        "default_model": "gpt-4.1-mini",
        "models": ["gpt-4.1-mini", "gpt-4.1", "o4-mini"],
    },
}

# In-memory conversation history per provider (ephemeral, session-scoped)
_histories: dict[str, list[dict]] = {}
_history_locks: dict[str, asyncio.Lock] = {}


def _history_key(provider: str, conversation_id: str | None = None) -> str:
    sid = current_session.get()
    suffix = conversation_id or "default"
    return f"{sid}:{provider}:{suffix}"


def _history_lock(key: str) -> asyncio.Lock:
    if key not in _history_locks:
        _history_locks[key] = asyncio.Lock()
    return _history_locks[key]


# LiteLLM discovery
_litellm_url = os.environ.get("LITELLM_URL", "").rstrip("/")
_litellm_port = os.environ.get("LITELLM_PORT", "")
if _litellm_url and _litellm_port:
    _litellm_url = f"{_litellm_url}:{_litellm_port}"
_litellm_key = os.environ.get("LITELLM_KEY", "")


def discover_litellm() -> dict:
    """(Re-)discover LiteLLM models. Returns status dict."""
    if not _litellm_url or not _litellm_key:
        return {"error": "LITELLM_URL or LITELLM_KEY not set"}
    try:
        import httpx
        r = httpx.get(f"{_litellm_url}/v1/models",
                      headers={"Authorization": f"Bearer {_litellm_key}"}, timeout=10, verify=False)
        if r.status_code == 200:
            models = [m["id"] for m in r.json().get("data", [])]
            if models:
                PROVIDERS["litellm"] = {
                    "name": "LiteLLM",
                    "env_key": "LITELLM_KEY",
                    "base_url": f"{_litellm_url}/v1/chat/completions",
                    "default_model": models[0],
                    "models": models,
                }
                print(f"[LiteLLM] discovered {len(models)} models: {', '.join(models[:5])}")
                return {"ok": True, "models": models}
            return {"error": "No models found"}
        return {"error": f"HTTP {r.status_code}"}
    except Exception as e:
        return {"error": str(e)}


# Auto-discover at import time
if _litellm_url and _litellm_key:
    _result = discover_litellm()
    if "error" in _result:
        print(f"[LiteLLM] discovery error: {_result['error']}")


def available_providers() -> list[dict]:
    """Return providers that have an API key configured."""
    result = []
    for pid, cfg in PROVIDERS.items():
        key = os.environ.get(cfg["env_key"], "")
        if key:
            result.append({
                "id": pid,
                "name": cfg["name"],
                "models": cfg["models"],
                "default_model": cfg["default_model"],
            })
    return result


def get_history(provider: str, conversation_id: str | None = None) -> list[dict]:
    hkey = _history_key(provider, conversation_id)
    return _histories.get(hkey, [])


def clear_history(provider: str, conversation_id: str | None = None) -> None:
    sid = current_session.get()
    if conversation_id:
        hkey = _history_key(provider, conversation_id)
        _histories[hkey] = []
        return
    prefix = f"{sid}:{provider}"
    for key in list(_histories):
        if key == prefix or key.startswith(f"{prefix}:"):
            _histories[key] = []


async def chat(
    provider: str,
    message: str,
    model: str | None = None,
    directives: list[str] | None = None,
    lang: str | None = None,
    stateless: bool = False,
    conversation_id: str | None = None,
) -> dict:
    """Send a chat completion request. Returns dict with 'reply' or 'error'."""
    cfg = PROVIDERS.get(provider)
    if not cfg:
        return {"error": f"Unknown provider: {provider}"}

    key = os.environ.get(cfg["env_key"], "")
    if not key:
        return {"error": f"No API key for {cfg['name']} — set {cfg['env_key']} in .env"}

    use_model = model or cfg["default_model"]

    # Prepend system message: language instruction + directives
    system_messages = []
    system_parts = []
    if lang:
        system_parts.append(f"Always respond in {lang}.")
    if directives:
        system_parts.extend(directives)
    if system_parts:
        system_messages.append({"role": "system", "content": "\n".join(system_parts)})

    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    async def send_payload(messages: list[dict]) -> tuple[httpx.Response | None, str | None]:
        skip_ssl = cfg["base_url"].startswith(_litellm_url) if _litellm_url else False
        async with httpx.AsyncClient(timeout=60.0, verify=not skip_ssl) as client:
            resp = await client.post(
                cfg["base_url"], headers=headers,
                json={"model": use_model, "messages": messages},
            )
        return resp, None

    try:
        if stateless:
            messages = system_messages + [{"role": "user", "content": message}]
            print(f"[CHAT] {provider}/{use_model} stateless=True hist=0")
            resp, _ = await send_payload(messages)
            if resp is None:
                return {"error": "No response"}
            if resp.status_code != 200:
                return {"error": resp.text, "status": resp.status_code}
            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
            return {"reply": reply, "model": use_model, "provider": provider}

        hkey = _history_key(provider, conversation_id)
        async with _history_lock(hkey):
            history = _histories.setdefault(hkey, [])
            user_entry = {"role": "user", "content": message}
            history.append(user_entry)
            messages = system_messages + history
            print(f"[CHAT] {provider}/{use_model} stateless=False hist={len(history)}")
            try:
                resp, _ = await send_payload(messages)
            except Exception:
                if history and history[-1] is user_entry:
                    history.pop()
                raise

            if resp is None:
                if history and history[-1] is user_entry:
                    history.pop()
                return {"error": "No response"}
            if resp.status_code != 200:
                if history and history[-1] is user_entry:
                    history.pop()
                return {"error": resp.text, "status": resp.status_code}

            data = resp.json()
            reply = data["choices"][0]["message"]["content"]
            history.append({"role": "assistant", "content": reply})

            return {"reply": reply, "model": use_model, "provider": provider}

    except Exception as e:
        return {"error": str(e)}
