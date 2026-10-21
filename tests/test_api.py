from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.main import app


def test_health_endpoint() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_chat_endpoint_returns_answer_and_citations(monkeypatch) -> None:
    service = SimpleNamespace(
        chat=lambda question, history: {
            "answer": f"תשובה: {question}",
            "citations": [{"title": "מקור", "url": "https://example.com/page"}],
        }
    )
    monkeypatch.setattr(app.state, "chat_service", service, raising=False)

    response = TestClient(app).post(
        "/chat",
        json={"question": "מה כתוב?", "history": [{"role": "user", "content": "שלום"}]},
    )

    assert response.status_code == 200
    assert response.json() == {
        "answer": "תשובה: מה כתוב?",
        "citations": [{"title": "מקור", "url": "https://example.com/page"}],
    }


def test_chat_endpoint_validates_empty_question() -> None:
    response = TestClient(app).post("/chat", json={"question": "   "})

    assert response.status_code == 422


def test_chat_endpoint_hides_dependency_error_details(monkeypatch) -> None:
    def fail(_question, _history):
        raise RuntimeError("secret upstream response detail")

    monkeypatch.setattr(app.state, "chat_service", SimpleNamespace(chat=fail), raising=False)

    response = TestClient(app).post("/chat", json={"question": "שאלה"})

    assert response.status_code == 503
    assert "secret upstream" not in response.text
