"""Minimal OpenRouter chat-completions client for optional LLM fallback."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests

from backend.check_setup import read_local_env

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "google/gemma-4-26b-a4b-it:free"


@dataclass(frozen=True)
class OpenRouterSettings:
    """OpenRouter credentials and model configuration."""

    api_key: str
    model: str = DEFAULT_OPENROUTER_MODEL
    site_url: str = ""
    app_name: str = "Hebrew RAG Chatbot"

    @classmethod
    def from_env(cls) -> OpenRouterSettings | None:
        """Load optional configuration; return None when fallback is not enabled."""
        local_env = read_local_env()
        api_key = os.environ.get("OPENROUTER_API_KEY") or local_env.get("OPENROUTER_API_KEY", "")
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            model=(
                os.environ.get("OPENROUTER_MODEL")
                or local_env.get("OPENROUTER_MODEL")
                or DEFAULT_OPENROUTER_MODEL
            ),
            site_url=os.environ.get("OPENROUTER_SITE_URL") or local_env.get("OPENROUTER_SITE_URL", ""),
            app_name=(
                os.environ.get("OPENROUTER_APP_NAME")
                or local_env.get("OPENROUTER_APP_NAME")
                or "Hebrew RAG Chatbot"
            ),
        )


class OpenRouterClient:
    """Generate text through OpenRouter's OpenAI-compatible chat completions API."""

    def __init__(
        self,
        settings: OpenRouterSettings,
        *,
        session: Any | None = None,
        timeout: float = 30,
    ) -> None:
        self.settings = settings
        self.session = session or requests.Session()
        self.timeout = timeout

    def generate_content(self, *, contents: str, model: str | None = None) -> Any:
        """Return a response object with a ``text`` attribute, compatible with Gemini usage."""
        headers = {
            "Authorization": f"Bearer {self.settings.api_key}",
            "Content-Type": "application/json",
            "X-Title": self.settings.app_name,
        }
        if self.settings.site_url:
            headers["HTTP-Referer"] = self.settings.site_url
        response = self.session.post(
            OPENROUTER_API_URL,
            headers=headers,
            json={
                "model": model or self.settings.model,
                "messages": [{"role": "user", "content": contents}],
                "max_tokens": 2000,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        try:
            payload = response.json()
            text = payload["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("OpenRouter returned an invalid chat completion response.") from exc
        if isinstance(text, list):
            text = "".join(
                item.get("text", "") for item in text if isinstance(item, dict)
            )
        if not isinstance(text, str) or not text.strip():
            raise RuntimeError("OpenRouter returned an empty answer.")
        return type("OpenRouterResponse", (), {"text": text.strip()})()
