"""
tts.py — Text-to-Speech providers with dynamic discovery.
Supports xAI/Grok, ElevenLabs (official SDK), Google Cloud TTS (REST).
"""

import os

_LANG_TO_BCP47 = {
    "DE": "de", "EN-US": "en", "EN-GB": "en", "HR": "hr", "ES": "es",
    "FR": "fr", "IT": "it", "PT-BR": "pt-BR", "RU": "ru", "TR": "tr",
    "PL": "pl", "NL": "nl", "SV": "sv", "CS": "cs", "SK": "sk",
    "SL": "sl", "RO": "ro", "HU": "hu", "UK": "uk", "BG": "bg",
    "ZH": "zh", "JA": "ja", "KO": "ko",
}

_discovery_cache: dict[str, dict] = {}


def available_providers() -> list[str]:
    """Return list of TTS provider IDs that have API keys configured."""
    providers = []
    if os.environ.get("XAI_API_KEY"):
        providers.append("xai")
    if os.environ.get("ELEVENLABS_API_KEY"):
        providers.append("elevenlabs")
    if os.environ.get("GOOGLE_TTS_CREDENTIALS"):
        providers.append("google")
    return providers


def clear_cache():
    """Clear cached discovery data."""
    _discovery_cache.clear()


# ── xAI / Grok ──────────────────────────────────────────────────────────────


async def discover_xai() -> dict:
    if "xai" in _discovery_cache:
        return _discovery_cache["xai"]

    import httpx
    key = os.environ.get("XAI_API_KEY", "")
    voices = []
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.x.ai/v1/tts/voices",
                headers={"Authorization": f"Bearer {key}"},
            )
            if resp.status_code == 200:
                data = resp.json()
                for v in data.get("voices", data if isinstance(data, list) else []):
                    vid = v.get("voice_id") or v.get("id", "")
                    name = v.get("name", vid)
                    if vid:
                        voices.append({"id": vid, "name": name})
    except Exception:
        pass

    if not voices:
        voices = [
            {"id": "eve", "name": "Eve (energetic)"},
            {"id": "ara", "name": "Ara (warm)"},
            {"id": "rex", "name": "Rex (professional)"},
            {"id": "sal", "name": "Sal (balanced)"},
            {"id": "leo", "name": "Leo (authoritative)"},
        ]

    result = {"id": "xai", "name": "Grok", "voices": voices, "models": []}
    _discovery_cache["xai"] = result
    return result


async def synthesize_xai(text: str, lang: str, voice: str = "eve") -> dict:
    import httpx

    key = os.environ.get("XAI_API_KEY", "")
    if not key:
        return {"error": "No XAI_API_KEY set"}

    bcp_lang = _LANG_TO_BCP47.get(lang, "auto")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.x.ai/v1/tts",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json={
                    "text": text, "voice_id": voice, "language": bcp_lang,
                    "output_format": {"codec": "mp3", "sample_rate": 24000, "bit_rate": 128000},
                },
            )
    except Exception as e:
        return {"error": f"xAI TTS: {e}"}
    if resp.status_code != 200:
        return {"error": f"xAI TTS: {resp.status_code} {resp.text[:200]}"}
    return {"audio": resp.content, "content_type": "audio/mpeg"}


# ── ElevenLabs (official SDK) ───────────────────────────────────────────────


def _elevenlabs_client():
    from elevenlabs import ElevenLabs
    return ElevenLabs(api_key=os.environ.get("ELEVENLABS_API_KEY", ""))


async def discover_elevenlabs() -> dict:
    if "elevenlabs" in _discovery_cache:
        return _discovery_cache["elevenlabs"]

    voices = []
    models = []
    try:
        client = _elevenlabs_client()
        resp = client.voices.get_all()
        for v in resp.voices:
            voices.append({"id": v.voice_id, "name": v.name})
    except Exception:
        voices = [
            {"id": "21m00Tcm4TlvDq8ikWAM", "name": "Rachel"},
            {"id": "29vD33N1CtxCmqQRPOHJ", "name": "Drew"},
            {"id": "EXAVITQu4vr4xnSDxMaL", "name": "Bella"},
            {"id": "ErXwobaYiN019PkySvjV", "name": "Antoni"},
            {"id": "TxGEqnHWrfWFTfGW9XjX", "name": "Josh"},
            {"id": "pNInz6obpgDQGcFmaJgB", "name": "Adam"},
        ]

    try:
        client = _elevenlabs_client()
        resp = client.models.get_all()
        for m in resp:
            if hasattr(m, "can_do_text_to_speech") and m.can_do_text_to_speech:
                models.append({"id": m.model_id, "name": m.name})
            elif "eleven" in (m.model_id or ""):
                models.append({"id": m.model_id, "name": m.name})
    except Exception:
        models = [
            {"id": "eleven_multilingual_v2", "name": "Multilingual v2"},
            {"id": "eleven_turbo_v2_5", "name": "Turbo v2.5"},
            {"id": "eleven_flash_v2_5", "name": "Flash v2.5"},
        ]

    result = {"id": "elevenlabs", "name": "ElevenLabs", "voices": voices, "models": models}
    _discovery_cache["elevenlabs"] = result
    return result


async def synthesize_elevenlabs(text: str, lang: str, voice: str = "21m00Tcm4TlvDq8ikWAM", model: str = "eleven_multilingual_v2") -> dict:
    key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not key:
        return {"error": "No ELEVENLABS_API_KEY set"}

    try:
        client = _elevenlabs_client()
        audio_iter = client.text_to_speech.convert(
            voice_id=voice, text=text, model_id=model,
        )
        audio = b"".join(audio_iter)
        return {"audio": audio, "content_type": "audio/mpeg"}
    except Exception as e:
        return {"error": f"ElevenLabs: {e}"}


# ── Google Cloud TTS (official SDK) ─────────────────────────────────────────


def _google_credentials():
    """Load Google credentials from base64-encoded service account JSON in env."""
    import base64
    import json
    from google.oauth2 import service_account
    creds_b64 = os.environ.get("GOOGLE_TTS_CREDENTIALS", "")
    if not creds_b64:
        return None
    info = json.loads(base64.b64decode(creds_b64))
    return service_account.Credentials.from_service_account_info(info)


def _google_client():
    from google.cloud import texttospeech
    creds = _google_credentials()
    if not creds:
        return None
    return texttospeech.TextToSpeechClient(credentials=creds)


async def discover_google() -> dict:
    if "google" in _discovery_cache:
        return _discovery_cache["google"]

    voices = []
    try:
        client = _google_client()
        if client:
            resp = client.list_voices()
            for v in resp.voices:
                name = v.name
                langs = ", ".join(v.language_codes)
                gender = v.ssml_gender.name if v.ssml_gender else ""
                label = f"{name} ({langs}, {gender})"
                voices.append({"id": name, "name": label})
    except Exception:
        pass

    if not voices:
        voices = [{"id": "default", "name": "Default"}]

    result = {"id": "google", "name": "Google", "voices": voices, "models": []}
    _discovery_cache["google"] = result
    return result


async def synthesize_google(text: str, lang: str, voice: str = "") -> dict:
    try:
        creds = _google_credentials()
        if not creds:
            return {"error": "No GOOGLE_TTS_CREDENTIALS set"}
        from google.cloud import texttospeech
        client = texttospeech.TextToSpeechClient(credentials=creds)

        bcp_lang = _LANG_TO_BCP47.get(lang, "en")
        voice_cfg = texttospeech.VoiceSelectionParams(language_code=bcp_lang)
        if voice and voice != "default":
            voice_cfg = texttospeech.VoiceSelectionParams(language_code=bcp_lang, name=voice)

        audio_config = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
        resp = client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=text),
            voice=voice_cfg,
            audio_config=audio_config,
        )
        return {"audio": resp.audio_content, "content_type": "audio/mpeg"}
    except Exception as e:
        return {"error": f"Google TTS: {e}"}


# ── Dispatch ─────────────────────────────────────────────────────────────────

_DISCOVER = {"xai": discover_xai, "elevenlabs": discover_elevenlabs, "google": discover_google}
_SYNTH = {"xai": synthesize_xai, "elevenlabs": synthesize_elevenlabs, "google": synthesize_google}


async def discover(provider: str) -> dict:
    fn = _DISCOVER.get(provider)
    if not fn:
        return {"error": f"Unknown provider: {provider}"}
    return await fn()


async def synthesize(provider: str, text: str, lang: str, voice: str | None = None, model: str | None = None) -> dict:
    if provider == "xai":
        return await synthesize_xai(text, lang, voice=voice or "eve")
    elif provider == "elevenlabs":
        return await synthesize_elevenlabs(text, lang, voice=voice or "21m00Tcm4TlvDq8ikWAM", model=model or "eleven_multilingual_v2")
    elif provider == "google":
        return await synthesize_google(text, lang, voice=voice or "")
    return {"error": f"Unknown provider: {provider}"}


async def check(provider: str) -> dict:
    result = await synthesize(provider, "test", "EN")
    if "error" in result:
        return result
    return {"ok": True}
