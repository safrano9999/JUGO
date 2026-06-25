"""
chat.py - LLM chat completion through configured OpenAI v1 endpoints.
Returns plain dicts, no HTTP dependencies.
"""

import asyncio
from console import current_session
from python_header import openai_v1_async_client, openai_v1_client, openai_v1_providers


# Provider configs. Chat and LLM translation intentionally go through OpenAI v1 only.
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


def discover_openai_v1() -> dict:
    """(Re-)discover OpenAI v1 providers. Returns status dict."""
    providers = openai_v1_providers()
    for provider_key in list(PROVIDERS):
        if provider_key.startswith("openai_v1"):
            PROVIDERS.pop(provider_key, None)
    if not providers:
        return {"error": "OPENAI_V1_URL is not set"}

    discovered: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    for provider in providers:
        try:
            client = openai_v1_client(provider, timeout=10.0)
            response = client.models.list()
            models = sorted({m.id for m in response.data if getattr(m, "id", "")})
            if not models:
                errors[provider.key] = "No models found"
                continue
            PROVIDERS[provider.key] = {
                "name": provider.label,
                "env_key": f"{provider.env_prefix}_KEY",
                "provider": provider,
                "base_url": provider.base_url,
                "api_key": provider.api_key,
                "default_model": models[0],
                "models": models,
            }
            discovered[provider.key] = models
            print(f"[{provider.label}] discovered {len(models)} models: {', '.join(models[:5])}")
        except Exception as e:
            errors[provider.key] = str(e)
    if discovered:
        return {"ok": True, "providers": discovered, "errors": errors}
    return {"error": "; ".join(f"{key}: {value}" for key, value in errors.items()) or "No models found"}


# Auto-discover at import time
if openai_v1_providers():
    _result = discover_openai_v1()
    if "error" in _result:
        print(f"[OpenAI v1] discovery error: {_result['error']}")


def available_providers() -> list[dict]:
    """Return configured OpenAI v1 providers with discovered models."""
    if not any(key.startswith("openai_v1") for key in PROVIDERS) and openai_v1_providers():
        discover_openai_v1()
    return [
        {
            "id": provider_id,
            "name": cfg["name"],
            "models": cfg["models"],
            "default_model": cfg["default_model"],
        }
        for provider_id, cfg in PROVIDERS.items()
        if provider_id.startswith("openai_v1")
    ]


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
        client = openai_v1_async_client(cfg["provider"], timeout=60.0)
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
