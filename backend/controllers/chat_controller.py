"""FastAPI routes for chat requests."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request, status

from backend.models.schemas import ChatRequest, ChatResponse

router = APIRouter()


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
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The chatbot could not complete the request. Please try again later.",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="A required AI or data service is temporarily unavailable.",
        ) from exc
