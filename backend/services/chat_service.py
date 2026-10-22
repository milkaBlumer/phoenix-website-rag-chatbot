"""Orchestrate conversation context, retrieval, and grounded answer generation."""

from __future__ import annotations

import copy
import logging
from collections import OrderedDict
from threading import Lock
from typing import Any

from backend.models.schemas import ChatMessage
from backend.services.safety_policy import assess_question

logger = logging.getLogger("backend.chat")

MAX_HISTORY_MESSAGES = 6
MAX_HISTORY_CHARS = 12_000
ANSWER_CACHE_SIZE = 128


class ChatService:
    """Coordinate RAG services and use prior turns for follow-up questions."""

    def __init__(
        self,
        retrieval_service: Any | None = None,
        generation_service: Any | None = None,
    ) -> None:
        if retrieval_service is None:
            from backend.services.retrieval_service import RetrievalService

            retrieval_service = RetrievalService()
        if generation_service is None:
            from backend.services.generation_service import GenerationService

            generation_service = GenerationService()
        self.retrieval_service = retrieval_service
        self.generation_service = generation_service
        self._answer_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._cache_lock = Lock()
    @staticmethod
    def _normalize_history(history: list[ChatMessage | dict[str, str]]) -> list[ChatMessage]:
        """Validate history and keep the most recent bounded conversation messages."""
        messages = [
            item if isinstance(item, ChatMessage) else ChatMessage.model_validate(item)
            for item in history
        ]
        selected: list[ChatMessage] = []
        total_chars = 0
        for message in reversed(messages[-MAX_HISTORY_MESSAGES:]):
            if total_chars + len(message.content) > MAX_HISTORY_CHARS:
                remaining = MAX_HISTORY_CHARS - total_chars
                if remaining <= 0:
                    break
                message = message.model_copy(update={"content": message.content[-remaining:]})
            selected.append(message)
            total_chars += len(message.content)
        return list(reversed(selected))

    def chat(
        self,
        question: str,
        history: list[ChatMessage | dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Answer one turn, using bounded history for query retrieval and context."""
        if not isinstance(question, str):
            raise TypeError("Question must be a string.")
        question = question.strip()
        if not question:
            raise ValueError("Question must not be empty or whitespace-only.")
        safety_decision = assess_question(question)
        if safety_decision is not None:
            return {"answer": safety_decision.answer, "citations": []}
        history_messages = self._normalize_history(history or [])
        cache_key = question.casefold() if not history_messages else None
        if cache_key is not None:
            with self._cache_lock:
                cached = self._answer_cache.get(cache_key)
                if cached is not None:
                    self._answer_cache.move_to_end(cache_key)
                    return copy.deepcopy(cached)
        if history_messages:
            try:
                retrieval_question = self.generation_service.rewrite_question(
                    question,
                    [
                        {"role": message.role, "content": message.content}
                        for message in history_messages
                    ],
                )
            except Exception:
                logger.warning("rewrite_question failed; using original question", exc_info=True)
                retrieval_question = question
        else:
            retrieval_question = question
        sources = self.retrieval_service.retrieve(retrieval_question)
        result = self.generation_service.generate(question, sources)
        answer = result.get("answer")
        citations = result.get("citations", [])
        if not isinstance(answer, str) or not answer.strip():
            raise RuntimeError("Generation service returned an empty answer.")
        if not isinstance(citations, list):
            citations = []
        response = {"answer": answer.strip(), "citations": citations}
        if cache_key is not None:
            with self._cache_lock:
                self._answer_cache[cache_key] = copy.deepcopy(response)
                if len(self._answer_cache) > ANSWER_CACHE_SIZE:
                    self._answer_cache.popitem(last=False)
        return response
