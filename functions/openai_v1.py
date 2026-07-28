"""OpenAI-v1 provider discovery, clients, models, and safe stream consumption."""

from __future__ import annotations

import inspect
import os
import re
from collections.abc import AsyncIterable, Iterable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from python_header import env as _loaded_env  # noqa: F401 — load config and environment


@dataclass(frozen=True)
class OpenAIV1Provider:
    index: int
    suffix: str
    env_prefix: str
    provider: str
    base_url: str
    api_key: str
    stream: bool

    @property
    def key(self) -> str:
        return "openai_v1" if self.index == 1 else f"openai_v1_{self.index}"

    @property
    def label(self) -> str:
        return "OpenAI v1" if self.index == 1 else f"OpenAI v1 #{self.index}"


def _clean_openai_v1(value: str | None) -> str:
    return (value or "").strip().strip('"').strip("'")


def _openai_v1_bool(value: str | None, default: bool = False) -> bool:
    cleaned = _clean_openai_v1(value).lower()
    if not cleaned:
        return default
    if cleaned in {"1", "true", "yes", "on"}:
        return True
    if cleaned in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid OpenAI v1 boolean value: {value!r}")


def _normalize_openai_v1_base_url(raw_url: str, raw_port: str = "") -> str:
    url = _clean_openai_v1(raw_url).rstrip("/")
    port = _clean_openai_v1(raw_port)
    if not url:
        return ""
    if "://" not in url:
        url = f"http://{url}"

    parsed = urlsplit(url)
    try:
        has_port = parsed.port is not None
    except ValueError:
        has_port = False

    netloc = parsed.netloc
    if port and not has_port:
        netloc = f"{netloc}:{port}"

    path = parsed.path.rstrip("/")
    base = urlunsplit((parsed.scheme, netloc, path, "", "")).rstrip("/")
    return base if path else f"{base}/v1"


def _openai_v1_suffixes(values: dict[str, str]) -> list[tuple[int, str]]:
    indexes = {1}
    pattern = re.compile(r"^OPENAI_V1_(?:PROVIDER|URL|PORT|KEY|STREAM)_(\d+)$")
    for key in values:
        match = pattern.match(key)
        if match:
            indexes.add(int(match.group(1)))
    return [(index, "" if index == 1 else f"_{index}") for index in sorted(indexes)]


def openai_v1_env_name(
    field: str,
    index: int,
    values: dict[str, str] | None = None,
) -> str:
    source = os.environ if values is None else values
    field = field.strip().upper()
    if index == 1:
        return f"OPENAI_V1_{field}"

    names = [f"OPENAI_V1_{field}_{index}", f"OPENAI_V1_{field}_{index:02d}"]
    pattern = re.compile(rf"^OPENAI_V1_{re.escape(field)}_(\d+)$")
    names.extend(
        name
        for name in sorted(source)
        if (match := pattern.match(name)) and int(match.group(1)) == index and name not in names
    )
    for name in names:
        if source.get(name):
            return name
    for name in names:
        if name in source:
            return name
    return names[0]


def _openai_v1_value(source: dict[str, str], field: str, index: int) -> str:
    return source.get(openai_v1_env_name(field, index, source), "")


def openai_v1_providers(values: dict[str, str] | None = None) -> list[OpenAIV1Provider]:
    source = dict(os.environ) if values is None else values
    providers: list[OpenAIV1Provider] = []
    for index, suffix in _openai_v1_suffixes(source):
        base_url = _normalize_openai_v1_base_url(
            _openai_v1_value(source, "URL", index),
            _openai_v1_value(source, "PORT", index),
        )
        if not base_url:
            continue
        providers.append(
            OpenAIV1Provider(
                index=index,
                suffix=suffix,
                env_prefix=f"OPENAI_V1{suffix}",
                provider=_clean_openai_v1(_openai_v1_value(source, "PROVIDER", index)),
                base_url=base_url,
                api_key=_clean_openai_v1(_openai_v1_value(source, "KEY", index)),
                stream=_openai_v1_bool(_openai_v1_value(source, "STREAM", index)),
            )
        )
    return providers


def openai_v1_first_provider(values: dict[str, str] | None = None) -> OpenAIV1Provider | None:
    providers = openai_v1_providers(values)
    return providers[0] if providers else None


def openai_v1_client(provider: OpenAIV1Provider | None = None, *, timeout: float = 60.0):
    provider = provider or openai_v1_first_provider()
    if provider is None:
        raise RuntimeError("OPENAI_V1_URL is not configured.")
    try:
        from openai import OpenAI
    except ImportError as exc:
        raise RuntimeError("Python package 'openai' is required for OpenAI v1 calls.") from exc
    return OpenAI(api_key=provider.api_key or "not-needed", base_url=provider.base_url, timeout=timeout)


def openai_v1_async_client(provider: OpenAIV1Provider | None = None, *, timeout: float = 60.0):
    provider = provider or openai_v1_first_provider()
    if provider is None:
        raise RuntimeError("OPENAI_V1_URL is not configured.")
    try:
        from openai import AsyncOpenAI
    except ImportError as exc:
        raise RuntimeError("Python package 'openai' is required for OpenAI v1 calls.") from exc
    return AsyncOpenAI(api_key=provider.api_key or "not-needed", base_url=provider.base_url, timeout=timeout)


def openai_v1_models(provider: OpenAIV1Provider | None = None, *, timeout: float = 10.0) -> list[str]:
    client = openai_v1_client(provider, timeout=timeout)
    response = client.models.list()
    return sorted({model.id for model in response.data if getattr(model, "id", "")})


def openai_v1_provider_models(
    values: dict[str, str] | None = None,
    *,
    timeout: float = 10.0,
) -> dict[OpenAIV1Provider, list[str]]:
    result: dict[OpenAIV1Provider, list[str]] = {}
    for provider in openai_v1_providers(values):
        result[provider] = openai_v1_models(provider, timeout=timeout)
    return result


def openai_v1_provider_for_model(
    model: str,
    values: dict[str, str] | None = None,
    *,
    timeout: float = 10.0,
) -> OpenAIV1Provider | None:
    providers = openai_v1_providers(values)
    if not providers:
        return None
    if len(providers) == 1:
        return providers[0]

    wanted = (model or "").strip()
    for provider in providers:
        try:
            if wanted in openai_v1_models(provider, timeout=timeout):
                return provider
        except Exception:
            continue
    return providers[0]


def _append_delta(buffer: bytearray, chunk: Any) -> None:
    for choice in getattr(chunk, "choices", ()):
        content = getattr(getattr(choice, "delta", None), "content", None)
        if isinstance(content, str):
            buffer.extend(content.encode("utf-8"))


def wipe_bytearray(buffer: bytearray) -> None:
    """Overwrite a mutable buffer before releasing its storage."""
    buffer[:] = b"\0" * len(buffer)
    buffer.clear()


@contextmanager
def openai_v1_stream_buffer(response: Iterable[Any]):
    """Yield a mutable UTF-8 buffer and zero it immediately after use."""
    buffer = bytearray()
    try:
        for chunk in response:
            _append_delta(buffer, chunk)
            del chunk
        yield buffer
    finally:
        wipe_bytearray(buffer)
        close = getattr(response, "close", None)
        if callable(close):
            close()


def consume_openai_v1_stream(response: Iterable[Any]) -> str:
    """Return concatenated text deltas while keeping raw chunks memory-only."""
    with openai_v1_stream_buffer(response) as buffer:
        return buffer.decode("utf-8").strip()


async def consume_openai_v1_stream_async(response: AsyncIterable[Any]) -> str:
    """Async variant of consume_openai_v1_stream."""
    buffer = bytearray()
    try:
        async for chunk in response:
            _append_delta(buffer, chunk)
            del chunk
        return buffer.decode("utf-8").strip()
    finally:
        wipe_bytearray(buffer)
        close = getattr(response, "aclose", None) or getattr(response, "close", None)
        if callable(close):
            result = close()
            if inspect.isawaitable(result):
                await result
