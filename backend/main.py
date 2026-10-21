"""FastAPI application entry point for the Hebrew RAG chatbot."""

from __future__ import annotations

import logging
from time import perf_counter

from fastapi import FastAPI

from backend.controllers.chat_controller import router as chat_router
from backend.utils.structured_logging import configure_logging

configure_logging()
logger = logging.getLogger("backend.api")

app = FastAPI(
    title="Hebrew RAG Chatbot API",
    description="A retrieval-augmented chatbot API that answers using its source website.",
    version="0.1.0",
)
app.include_router(chat_router)


@app.middleware("http")
async def log_http_request(request, call_next):
    """Log request metadata and duration, never bodies, query strings, or exception text."""
    started_at = perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.error(
            "http_request_failed",
            extra={
                "event": "http_request_failed",
                "method": request.method,
                "path": request.url.path,
                "status_code": 500,
                "duration_ms": round((perf_counter() - started_at) * 1000, 2),
                "error_type": type(exc).__name__,
            },
        )
        raise
    logger.info(
        "http_request_complete",
        extra={
            "event": "http_request_complete",
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round((perf_counter() - started_at) * 1000, 2),
        },
    )
    return response


@app.get("/health")
def health() -> dict[str, str]:
    """Simple liveness check that does not require external API credentials."""
    return {"status": "ok"}
