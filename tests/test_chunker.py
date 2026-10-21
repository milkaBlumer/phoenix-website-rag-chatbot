from __future__ import annotations

import json

import pytest

from backend.ingestion.chunker import chunk_text, chunks_from_page, load_pages, write_chunks


def test_cleans_and_chunks_hebrew_text_with_bounded_overlap() -> None:
    text = "  שלום   עולם.\n\nזו פסקה נוספת עם טקסט בעברית. " * 8

    chunks = chunk_text(text, max_chars=45, overlap=8)

    assert len(chunks) > 1
    assert all(0 < len(chunk) <= 45 for chunk in chunks)
    assert all("  " not in chunk for chunk in chunks)
    assert "שלום עולם." in " ".join(chunks)


def test_rejects_invalid_chunk_limits() -> None:
    with pytest.raises(ValueError):
        chunk_text("טקסט", max_chars=0)
    with pytest.raises(ValueError):
        chunk_text("טקסט", max_chars=10, overlap=10)


def test_chunk_ids_are_stable_and_change_with_content() -> None:
    page = {"url": "https://example.com/page", "title": "דוגמה", "text": "טקסט ראשון."}

    first = chunks_from_page(page, max_chars=100, overlap=10)
    repeated = chunks_from_page(page, max_chars=100, overlap=10)
    changed = chunks_from_page({**page, "text": "טקסט אחר."}, max_chars=100, overlap=10)

    assert first[0].chunk_id == repeated[0].chunk_id
    assert first[0].chunk_id != changed[0].chunk_id


def test_chunk_json_round_trip(tmp_path) -> None:
    pages_dir = tmp_path / "raw"
    pages_dir.mkdir()
    (pages_dir / "page.json").write_text(
        json.dumps({"url": "https://example.com", "title": "דף", "text": "תוכן."}, ensure_ascii=False),
        encoding="utf-8",
    )
    chunks = chunks_from_page(
        {"url": "https://example.com", "title": "דף", "text": "תוכן."},
        max_chars=100,
        overlap=10,
    )
    output = tmp_path / "chunks" / "chunks.json"

    write_chunks(chunks, output)

    assert load_pages(pages_dir)[0]["title"] == "דף"
    assert json.loads(output.read_text(encoding="utf-8"))[0]["text"] == "תוכן."
