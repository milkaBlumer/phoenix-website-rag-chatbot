from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.services.embedding_service import EmbeddingService, EmbeddingSettings
from backend.services.retrieval_service import RetrievalService, RetrievalSettings


def test_embedding_service_batches_documents_and_checks_dimensions() -> None:
    calls: list[dict] = []

    def embed_content(**kwargs):
        calls.append(kwargs)
        contents = kwargs["contents"]
        return SimpleNamespace(
            embeddings=[SimpleNamespace(values=[0.1, 0.2, 0.3]) for _ in contents]
        )

    service = EmbeddingService(
        client=SimpleNamespace(models=SimpleNamespace(embed_content=embed_content)),
        settings=EmbeddingSettings(api_key="test-key", model="test-model", output_dimensionality=3),
        batch_size=2,
    )

    vectors = service.embed_texts(["טקסט א", "טקסט ב", "טקסט ג"])

    assert len(vectors) == 3
    assert [len(call["contents"]) for call in calls] == [2, 1]
    assert all(call["config"].task_type == "RETRIEVAL_DOCUMENT" for call in calls)


def test_embedding_service_rejects_empty_and_malformed_vectors() -> None:
    service = EmbeddingService(
        client=SimpleNamespace(
            models=SimpleNamespace(
                embed_content=lambda **_kwargs: SimpleNamespace(
                    embeddings=[SimpleNamespace(values=[0.1])]
                )
            )
        ),
        settings=EmbeddingSettings(api_key="test-key", output_dimensionality=3),
    )

    with pytest.raises(ValueError, match="must not be empty"):
        service.embed_texts([" "])
    with pytest.raises(RuntimeError, match="expected 3"):
        service.embed_query("שאלה")


def test_retrieval_service_filters_and_normalizes_results() -> None:
    embedding = SimpleNamespace(embed_query=lambda question: [0.1, 0.2])
    repository = SimpleNamespace(
        search=lambda vector, limit: [
            {
                "id": "relevant",
                "url": "https://example.com/relevant",
                "title": "רלוונטי",
                "content": "תוכן רלוונטי",
                "similarity": 0.91,
            },
            {
                "id": "weak",
                "url": "https://example.com/weak",
                "content": "תוכן חלש",
                "similarity": 0.4,
            },
        ]
    )
    service = RetrievalService(
        embedding,
        repository,
        settings=RetrievalSettings(top_k=4, relevance_threshold=0.7),
    )

    results = service.retrieve("  שאלה בעברית  ")

    assert len(results) == 1
    assert results[0]["text"] == "תוכן רלוונטי"
    assert results[0]["similarity"] == 0.91
