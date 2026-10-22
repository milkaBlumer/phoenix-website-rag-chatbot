from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from backend.main import app


def test_health_endpoint() -> None:
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_allows_deployed_frontend_preflight() -> None:
    response = TestClient(app).options(
        "/chat",
        headers={
            "Origin": "https://phoenix-website-rag-chatbot.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "https://phoenix-website-rag-chatbot.vercel.app"
    )


def test_cors_does_not_allow_other_origins() -> None:
    response = TestClient(app).options(
        "/chat",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert "access-control-allow-origin" not in response.headers


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


def test_chat_endpoint_reports_quota_errors_as_429(monkeypatch) -> None:
    class QuotaError(Exception):
        code = 429

    def fail(_question, _history):
        raise QuotaError("RESOURCE_EXHAUSTED")

    monkeypatch.setattr(app.state, "chat_service", SimpleNamespace(chat=fail), raising=False)

    response = TestClient(app).post("/chat", json={"question": "שאלה"})

    assert response.status_code == 429
    assert response.json()["detail"]["code"] == "quota_exceeded"


def test_chat_endpoint_reports_unexpected_errors_as_502(monkeypatch) -> None:
    def fail(_question, _history):
        raise ConnectionError("db down")

    monkeypatch.setattr(app.state, "chat_service", SimpleNamespace(chat=fail), raising=False)

    response = TestClient(app).post("/chat", json={"question": "שאלה"})

    assert response.status_code == 502
    assert response.json()["detail"]["error_type"] == "ConnectionError"
