"""
LLM provider abstraction for the dataset chatbot (spec §14).

One function — chat_completion() — dispatches to the configured provider. Groq,
Mistral, and Ollama all speak the OpenAI-compatible /chat/completions shape, so
switching providers is a single config change (CHAT_PROVIDER). Degrades to a
deterministic stub when no key is set, so the feature is demoable offline.
"""
import logging
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def _openai_compatible(base_url: str, api_key: str, model: str, system: str, messages: list[dict]) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}, *messages],
        "temperature": 0.2,
        "max_tokens": 600,
    }
    resp = httpx.post(
        f"{base_url.rstrip('/')}/chat/completions",
        json=payload,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _stub(system: str, messages: list[dict]) -> str:
    """Deterministic offline answer so the chat flow works without an API key."""
    last = next((m["content"] for m in reversed(messages) if m["role"] == "user"), "")
    return (
        "⚙️ The dataset assistant isn't connected to a live model yet, so here's what "
        "I can tell you from the verification data:\n\n"
        f"{system}\n\n"
        f"(You asked: “{last}”. Configure a CHAT_PROVIDER API key to get conversational answers.)"
    )


def chat_completion(system: str, messages: list[dict]) -> str:
    """
    Run one chat completion against the configured provider.
    `system` carries the per-dataset context; `messages` is the OpenAI-style
    [{"role": "user"|"assistant", "content": ...}] conversation history.
    """
    provider = (settings.CHAT_PROVIDER or "groq").lower()
    try:
        if provider == "groq" and settings.GROQ_API_KEY:
            return _openai_compatible(settings.GROQ_BASE_URL, settings.GROQ_API_KEY, settings.GROQ_MODEL, system, messages)
        if provider == "mistral" and settings.MISTRAL_API_KEY:
            return _openai_compatible(settings.MISTRAL_BASE_URL, settings.MISTRAL_API_KEY, settings.MISTRAL_MODEL, system, messages)
        if provider == "ollama":
            # Ollama needs no key; base URL points at the local/self-hosted server.
            return _openai_compatible(settings.OLLAMA_BASE_URL, "ollama", settings.OLLAMA_MODEL, system, messages)
    except Exception as e:  # never surface a provider error as a 500 to the buyer
        logger.warning("Chat provider '%s' failed: %s", provider, e)
        return (
            "The dataset assistant is temporarily unavailable. Please try again shortly, "
            "or reach out to the seller through the request board."
        )

    return _stub(system, messages)
