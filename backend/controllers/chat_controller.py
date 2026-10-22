"""FastAPI routes for chat requests."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from backend.models.schemas import ChatRequest, ChatResponse
from backend.utils.retry import is_quota_exhausted

router = APIRouter()
logger = logging.getLogger("backend.api")


def _root_cause(error: BaseException) -> tuple[str, int | None]:
    """Return the innermost exception's class name and any HTTP status it carries."""
    current = error
    while current.__cause__ is not None or current.__context__ is not None:
        current = current.__cause__ or current.__context__
    value = getattr(current, "status_code", None) or getattr(current, "code", None)
    return type(current).__name__, value if isinstance(value, int) else None


def get_chat_service(request: Request) -> Any:
    """Return the app-scoped chat service, creating it lazily when needed."""
    service = getattr(request.app.state, "chat_service", None)
    if service is None:
        from backend.services.chat_service import ChatService

        service = ChatService()
        request.app.state.chat_service = service
    return service


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, request: Request) -> ChatResponse:
    """Return a grounded answer and its source citations."""
    try:
        result = get_chat_service(request).chat(
            payload.question,
            [message.model_dump() for message in payload.history],
        )
        return ChatResponse.model_validate(result)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        error_type, upstream_status = _root_cause(exc)
        logger.exception(
            "chat_failed",
            extra={
                "error_type": error_type,
                "upstream_status": upstream_status,
                "error_detail": str(exc.__cause__ or exc)[:500],
            },
        )
        if is_quota_exhausted(exc) or upstream_status == 429:
            status_code, code = status.HTTP_429_TOO_MANY_REQUESTS, "quota_exceeded"
        elif isinstance(exc, RuntimeError):
            status_code, code = status.HTTP_503_SERVICE_UNAVAILABLE, "generation_unavailable"
        else:
            status_code, code = status.HTTP_502_BAD_GATEWAY, "upstream_error"
        raise HTTPException(
            status_code=status_code,
            detail={
                "message": "The chatbot could not complete the request. Please try again later.",
                "code": code,
                "error_type": error_type,
                "upstream_status": upstream_status,
            },
        ) from exc
