from __future__ import annotations

from unittest.mock import Mock

import pytest

from backend.repositories.vector_repository import VectorRepository


def _record(embedding: list[float] | None = None) -> dict:
    return {
        "chunk_id": "chunk-1",
        "url": "https://example.com/page",
        "title": "דף",
        "chunk_index": 0,
        "text": "תוכן בעברית",
        "embedding": embedding if embedding is not None else [0.25] * 768,
    }


def test_maps_chunk_records_to_database_columns() -> None:
    mapped = VectorRepository._validate_record(_record())

    assert mapped["id"] == "chunk-1"
    assert mapped["content"] == "תוכן בעברית"
    assert mapped["url"] == "https://example.com/page"
    assert len(mapped["embedding"]) == 768
    assert "text" not in mapped


def test_rejects_embedding_with_wrong_dimensions() -> None:
    with pytest.raises(ValueError, match="768 dimensions"):
        VectorRepository._validate_record(_record([0.1, 0.2]))


def test_search_calls_match_rpc_and_returns_rows() -> None:
    client = Mock()
    client.rpc.return_value.execute.return_value.data = [
        {"id": "chunk-1", "url": "https://example.com/page", "similarity": 0.91}
    ]
    repository = VectorRepository(client=client)

    result = repository.search([0.1] * 768, limit=4)

    assert result[0]["similarity"] == 0.91
    client.rpc.assert_called_once_with(
        "match_documents",
        {"query_embedding": [0.1] * 768, "match_count": 4},
    )


def test_search_rejects_invalid_query_vector() -> None:
    repository = VectorRepository(client=Mock())

    with pytest.raises(ValueError, match="768 dimensions"):
        repository.search([0.1, 0.2])
