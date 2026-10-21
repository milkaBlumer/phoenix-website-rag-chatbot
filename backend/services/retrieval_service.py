"""Retrieve relevant source chunks for user questions using Gemini and Supabase."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from backend.check_setup import read_local_env

DEFAULT_TOP_K = 5
DEFAULT_RELEVANCE_THRESHOLD = 0.70


@dataclass(frozen=True)
class RetrievalSettings:
    """Runtime retrieval limits and relevance threshold."""

    top_k: int = DEFAULT_TOP_K
    relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD

    @classmethod
    def from_env(cls) -> RetrievalSettings:
        """Read retrieval settings from environment variables or the .env file."""
        local_env = read_local_env()
        top_k_value = os.environ.get("TOP_K") or local_env.get("TOP_K", str(DEFAULT_TOP_K))
        threshold_value = (
            os.environ.get("RELEVANCE_THRESHOLD")
            or local_env.get("RELEVANCE_THRESHOLD", str(DEFAULT_RELEVANCE_THRESHOLD))
        )
        try:
            top_k = int(top_k_value)
            threshold = float(threshold_value)
        except ValueError as exc:
            raise ValueError("TOP_K must be an integer and RELEVANCE_THRESHOLD must be numeric.") from exc
        if top_k < 1:
            raise ValueError("TOP_K must be at least 1.")
        if not 0 <= threshold <= 1:
            raise ValueError("RELEVANCE_THRESHOLD must be between 0 and 1.")
        return cls(top_k=top_k, relevance_threshold=threshold)


class RetrievalService:
    """Embed a query, retrieve candidate chunks, and filter low-similarity results."""

    def __init__(
        self,
        embedding_service: Any | None = None,
        repository: Any | None = None,
        *,
        settings: RetrievalSettings | None = None,
    ) -> None:
        self.settings = settings or RetrievalSettings.from_env()
        if embedding_service is None:
            from backend.services.embedding_service import EmbeddingService

            embedding_service = EmbeddingService()
        if repository is None:
            from backend.repositories.vector_repository import VectorRepository

            repository = VectorRepository()
        self.embedding_service = embedding_service
        self.repository = repository

    def retrieve_candidates(self, question: str, *, top_k: int | None = None) -> list[dict[str, Any]]:
        """Return validated similarity-ranked candidates without applying the threshold."""
        if not isinstance(question, str):
            raise TypeError("Question must be a string.")
        if not question.strip():
            raise ValueError("Question must not be empty or whitespace-only.")
        count = top_k if top_k is not None else self.settings.top_k
        if isinstance(count, bool) or count < 1:
            raise ValueError("top_k must be at least 1.")

        query_embedding = self.embedding_service.embed_query(question.strip())
        candidates = self.repository.search(query_embedding, limit=count)
        results: list[dict[str, Any]] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            try:
                similarity = float(candidate.get("similarity", 0.0))
            except (TypeError, ValueError):
                continue
            content = candidate.get("content")
            url = candidate.get("url")
            if not isinstance(content, str) or not content.strip() or not isinstance(url, str) or not url:
                continue
            results.append(
                {
                    "id": candidate.get("id"),
                    "url": url,
                    "title": candidate.get("title", ""),
                    "chunk_index": candidate.get("chunk_index", 0),
                    "text": content,
                    "similarity": similarity,
                }
            )
        return results

    def retrieve(self, question: str, *, top_k: int | None = None) -> list[dict[str, Any]]:
        """Return up to ``top_k`` chunks at or above the configured similarity threshold."""
        return [
            candidate
            for candidate in self.retrieve_candidates(question, top_k=top_k)
            if candidate["similarity"] >= self.settings.relevance_threshold
        ]
