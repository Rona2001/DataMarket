"""
LLM provider abstraction for the Datia assistant (spec §14).

Groq, Mistral and Ollama all speak the OpenAI-compatible /chat/completions
shape, so switching providers is a single config change (CHAT_PROVIDER).

  complete()  — one full answer (optionally JSON, optionally on the fast model)
  stream()    — the same answer as text deltas, for word-by-word display

Both raise LLMUnavailable when no provider is configured (callers fall back to
a deterministic offline answer) and LLMError when the provider call fails.
"""
import json
import logging
from typing import Iterator

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMError(Exception):
    """The provider was called and failed."""


class LLMUnavailable(LLMError):
    """No provider is configured (no API key)."""


def _provider(fast: bool = False) -> tuple[str, str, str]:
    """(base_url, api_key, model) for the configured provider."""
    provider = (settings.CHAT_PROVIDER or "groq").lower()
    if provider == "groq" and settings.GROQ_API_KEY:
        model = (settings.GROQ_FAST_MODEL or settings.GROQ_MODEL) if fast else settings.GROQ_MODEL
        return settings.GROQ_BASE_URL, settings.GROQ_API_KEY, model
    if provider == "mistral" and settings.MISTRAL_API_KEY:
        return settings.MISTRAL_BASE_URL, settings.MISTRAL_API_KEY, settings.MISTRAL_MODEL
    if provider == "ollama":
        # Ollama needs no key; base URL points at the local/self-hosted server.
        return settings.OLLAMA_BASE_URL, "ollama", settings.OLLAMA_MODEL
    raise LLMUnavailable(f"no API key for chat provider '{provider}'")


def is_configured() -> bool:
    try:
        _provider()
        return True
    except LLMUnavailable:
        return False


def _request(system: str, messages: list[dict], fast: bool, max_tokens: int, json_mode: bool, stream: bool):
    base_url, api_key, model = _provider(fast)
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, *messages],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    if model.startswith("openai/gpt-oss"):
        # Reasoning model: its thinking counts against max_tokens, so keep it short.
        payload["reasoning_effort"] = "low"
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    if stream:
        payload["stream"] = True
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    return url, headers, payload, model


def complete(
    system: str,
    messages: list[dict],
    *,
    fast: bool = False,
    max_tokens: int = 1200,
    json_mode: bool = False,
) -> str:
    """
    Run one chat completion. `system` carries the context; `messages` is the
    OpenAI-style [{"role": "user"|"assistant", "content": ...}] history.
    `fast` uses the small model, for helper calls such as query expansion.
    """
    url, headers, payload, model = _request(system, messages, fast, max_tokens, json_mode, stream=False)
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=30)
    except httpx.HTTPError as e:
        logger.warning("Chat provider call to %s failed: %s", model, e)
        raise LLMError(str(e))
    if resp.status_code >= 400:
        logger.warning("Chat provider %s from %s: %s", resp.status_code, model, resp.text[:500])
        raise LLMError(f"{resp.status_code} from {model}")
    content = (resp.json()["choices"][0]["message"].get("content") or "").strip()
    if not content:
        logger.warning("Chat provider returned an empty answer from %s", model)
        raise LLMError(f"empty answer from {model}")
    return content


def stream(system: str, messages: list[dict], *, max_tokens: int = 1200) -> Iterator[str]:
    """Same as complete(), yielding the answer as text deltas (server-sent events upstream)."""
    url, headers, payload, model = _request(system, messages, False, max_tokens, False, stream=True)
    got_text = False
    try:
        with httpx.stream("POST", url, json=payload, headers=headers, timeout=httpx.Timeout(60, connect=10)) as resp:
            if resp.status_code >= 400:
                resp.read()
                logger.warning("Chat provider %s from %s: %s", resp.status_code, model, resp.text[:500])
                raise LLMError(f"{resp.status_code} from {model}")
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    choices = json.loads(data).get("choices") or []
                except ValueError:
                    continue
                delta = (choices[0].get("delta") or {}).get("content") if choices else None
                if delta:
                    got_text = True
                    yield delta
    except httpx.HTTPError as e:
        logger.warning("Chat provider stream from %s failed: %s", model, e)
        raise LLMError(str(e))
    if not got_text:
        logger.warning("Chat provider returned an empty stream from %s", model)
        raise LLMError(f"empty answer from {model}")


def complete_json(system: str, messages: list[dict], *, max_tokens: int = 500) -> dict:
    """A small structured helper call on the fast model. Returns {} if the JSON is unusable."""
    raw = complete(system, messages, fast=True, max_tokens=max_tokens, json_mode=True)
    try:
        start, end = raw.index("{"), raw.rindex("}") + 1
        parsed = json.loads(raw[start:end])
        return parsed if isinstance(parsed, dict) else {}
    except ValueError:
        return {}
