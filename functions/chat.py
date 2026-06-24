"""
chat.py — LLM chat completion through LiteLLM's OpenAI-compatible endpoint.
Returns plain dicts, no HTTP dependencies.
"""

import os
import asyncio
from urllib.parse import urlsplit, urlunsplit
from console import current_session


# Provider configs. Chat and LLM translation intentionally go through LiteLLM only.
PROVIDERS: dict[str, dict] = {}

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


def _litellm_base_url() -> str:
    raw_url = os.environ.get("LITELLM_URL", "").strip().strip('"').strip("'").rstrip("/")
    raw_port = os.environ.get("LITELLM_PORT", "").strip().strip('"').strip("'")
    if not raw_url:
        return ""
    if "://" not in raw_url:
        raw_url = f"http://{raw_url}"
    if raw_url.endswith("/v1"):
        raw_url = raw_url[:-3].rstrip("/")
    parsed = urlsplit(raw_url)
    has_port = False
    try:
        has_port = parsed.port is not None
    except ValueError:
        has_port = False
    netloc = parsed.netloc
    if raw_port and not has_port:
        netloc = f"{netloc}:{raw_port}"
    base_url = urlunsplit((parsed.scheme, netloc, parsed.path.rstrip("/"), "", "")).rstrip("/")
    return f"{base_url}/v1"


def _litellm_api_key() -> str:
    return os.environ.get("LITELLM_API_KEY", "")


def _openai_client(base_url: str, api_key: str, timeout: float = 60.0):
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise RuntimeError("Python package 'openai' is required for LLM calls.") from exc
    return AsyncOpenAI(api_key=api_key or "not-needed", base_url=base_url, timeout=timeout)


def _sync_openai_client(base_url: str, api_key: str, timeout: float = 10.0):
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Python package 'openai' is required for model discovery.") from exc
    return OpenAI(api_key=api_key or "not-needed", base_url=base_url, timeout=timeout)


def discover_litellm() -> dict:
    """(Re-)discover LiteLLM models. Returns status dict."""
    litellm_base = _litellm_base_url()
    litellm_key = _litellm_api_key()
    if not litellm_base or not litellm_key:
        PROVIDERS.pop("litellm", None)
        return {"error": "LITELLM_URL or LITELLM_API_KEY not set"}
    try:
        client = _sync_openai_client(litellm_base, litellm_key, timeout=10.0)
        response = client.models.list()
        models = sorted({m.id for m in response.data if getattr(m, "id", "")})
        if models:
            PROVIDERS["litellm"] = {
                "name": "LiteLLM",
                "env_key": "LITELLM_API_KEY",
                "base_url": litellm_base,
                "default_model": models[0],
                "models": models,
            }
            print(f"[LiteLLM] discovered {len(models)} models: {', '.join(models[:5])}")
            return {"ok": True, "models": models}
        PROVIDERS.pop("litellm", None)
        return {"error": "No models found"}
    except Exception as e:
        PROVIDERS.pop("litellm", None)
        return {"error": str(e)}


# Auto-discover at import time
if _litellm_base_url() and _litellm_api_key():
    _result = discover_litellm()
    if "error" in _result:
        print(f"[LiteLLM] discovery error: {_result['error']}")


def available_providers() -> list[dict]:
    """Return the LiteLLM provider if it is configured and models were discovered."""
    if "litellm" not in PROVIDERS and _litellm_base_url() and _litellm_api_key():
        discover_litellm()
    cfg = PROVIDERS.get("litellm")
    if not cfg:
        return []
    return [{
        "id": "litellm",
        "name": cfg["name"],
        "models": cfg["models"],
        "default_model": cfg["default_model"],
    }]


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

    key = _litellm_api_key()
    if not key:
        return {"error": "No LiteLLM API key — set LITELLM_API_KEY in .env"}

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

    async def send_payload(messages: list[dict]) -> str:
        client = _openai_client(cfg["base_url"], key, timeout=60.0)
        response = await client.chat.completions.create(
            model=use_model,
            messages=messages,
        )
        content = response.choices[0].message.content
        if isinstance(content, list):
            content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        return (content or "").strip()

    try:
        if stateless:
            messages = system_messages + [{"role": "user", "content": message}]
            print(f"[CHAT] {provider}/{use_model} stateless=True hist=0")
            reply = await send_payload(messages)
            return {"reply": reply, "model": use_model, "provider": provider}

        hkey = _history_key(provider, conversation_id)
        async with _history_lock(hkey):
            history = _histories.setdefault(hkey, [])
            user_entry = {"role": "user", "content": message}
            history.append(user_entry)
            messages = system_messages + history
            print(f"[CHAT] {provider}/{use_model} stateless=False hist={len(history)}")
            try:
                reply = await send_payload(messages)
            except Exception:
                if history and history[-1] is user_entry:
                    history.pop()
                raise

            history.append({"role": "assistant", "content": reply})

            return {"reply": reply, "model": use_model, "provider": provider}

    except Exception as e:
        return {"error": str(e)}
