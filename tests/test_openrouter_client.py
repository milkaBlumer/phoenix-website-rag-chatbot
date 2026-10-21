from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

from backend.services.generation_service import GenerationService, GenerationSettings
from backend.services.openrouter_client import (
    DEFAULT_OPENROUTER_MODEL,
    OpenRouterClient,
    OpenRouterSettings,
)


def test_openrouter_client_sends_bearer_api_key() -> None:
    session = Mock()
    session.post.return_value.json.return_value = {
        "choices": [{"message": {"content": "תשובה"}}]
    }
    client = OpenRouterClient(
        OpenRouterSettings(api_key="test-key", model="test-model"),
        session=session,
    )

    response = client.generate_content(contents="prompt")

    assert response.text == "תשובה"
    assert session.post.call_args.kwargs["headers"]["Authorization"] == "Bearer test-key"


def test_default_openrouter_model_is_free() -> None:
    assert DEFAULT_OPENROUTER_MODEL.endswith(":free")


def test_generation_falls_back_to_openrouter_on_gemini_rate_limit() -> None:
    class RateLimitError(Exception):
        status_code = 429

    def generate_content(**_kwargs):
        raise RateLimitError("quota exceeded")

    backup_client = SimpleNamespace(
        generate_content=lambda **_kwargs: SimpleNamespace(text="תשובה מגיבוי")
    )
    service = GenerationService(
        client=SimpleNamespace(models=SimpleNamespace(generate_content=generate_content)),
        backup_client=backup_client,
        settings=GenerationSettings(api_key="test-key"),
    )

    response = service._generate_content("prompt")

    assert response.text == "תשובה מגיבוי"
