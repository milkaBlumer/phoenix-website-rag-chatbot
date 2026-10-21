from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.ingestion.embed_upload import embed_and_upload


def _chunks(count: int) -> list[dict[str, str]]:
    return [
        {"chunk_id": str(index), "url": "https://example.com", "text": "א" * 100}
        for index in range(count)
    ]


def test_embed_and_upload_batches_and_limits_estimated_token_rate() -> None:
    clock = 0.0
    delays: list[float] = []
    embed_calls: list[list[str]] = []
    saved_records: list[dict] = []

    def sleep(seconds: float) -> None:
        nonlocal clock
        delays.append(seconds)
        clock += seconds

    def embed_texts(texts: list[str]) -> list[list[float]]:
        nonlocal clock
        embed_calls.append(texts)
        clock += 1
        return [[0.1] * 768 for _ in texts]

    embedding = SimpleNamespace(dimensions=768, embed_texts=embed_texts)
    repository = SimpleNamespace(
        upsert_chunks=lambda records, batch_size: (saved_records.extend(records) or len(records))
    )

    uploaded = embed_and_upload(
        _chunks(3),
        embedding,
        repository,
        batch_size=2,
        max_estimated_tokens_per_minute=1_200,
        sleep=sleep,
        monotonic=lambda: clock,
    )

    assert uploaded == 3
    assert [len(call) for call in embed_calls] == [2, 1]
    assert len(saved_records) == 3
    assert delays == [19.0]


def test_embed_and_upload_rejects_invalid_rate_limit() -> None:
    embedding = SimpleNamespace(dimensions=768, embed_texts=lambda _texts: [])
    repository = SimpleNamespace(upsert_chunks=lambda _records, batch_size: 0)

    with pytest.raises(ValueError, match="at least 1"):
        embed_and_upload(_chunks(1), embedding, repository, max_estimated_tokens_per_minute=0)
