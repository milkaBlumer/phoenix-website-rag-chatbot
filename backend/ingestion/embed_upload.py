"""Embed chunk records with Gemini and upsert them to Supabase in batches."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from google.genai.errors import APIError as GeminiAPIError

from backend.repositories.vector_repository import EXPECTED_DIMENSIONS, VectorRepository
from backend.services.embedding_service import EmbeddingService
from backend.utils.retry import is_quota_exhausted

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_PATH = ROOT / "data" / "chunks" / "chunks.json"
DEFAULT_BATCH_SIZE = 5
DEFAULT_MAX_ESTIMATED_TOKENS_PER_MINUTE = 20_000
ESTIMATED_TOKENS_PER_CHARACTER = 2


def load_chunks(input_path: Path) -> list[dict[str, Any]]:
    """Load and validate chunk records needed for embedding and storage."""
    data = json.loads(input_path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TypeError("Chunk input must be a JSON array.")

    chunks: list[dict[str, Any]] = []
    for index, chunk in enumerate(data):
        if not isinstance(chunk, dict):
            raise TypeError(f"Chunk at index {index} must be a JSON object.")
        for field in ("chunk_id", "url", "text"):
            if not isinstance(chunk.get(field), str) or not chunk[field].strip():
                raise ValueError(f"Chunk at index {index} must have a non-empty '{field}' string.")
        title = chunk.get("title", "")
        chunk_index = chunk.get("chunk_index", index)
        if not isinstance(title, str):
            raise TypeError(f"Chunk at index {index} has a non-string title.")
        if isinstance(chunk_index, bool) or not isinstance(chunk_index, int) or chunk_index < 0:
            raise ValueError(f"Chunk at index {index} has an invalid chunk_index.")
        chunks.append(chunk)
    return chunks


def embed_and_upload(
    chunks: list[dict[str, Any]],
    embedding_service: EmbeddingService,
    repository: VectorRepository,
    batch_size: int = DEFAULT_BATCH_SIZE,
    max_estimated_tokens_per_minute: int = DEFAULT_MAX_ESTIMATED_TOKENS_PER_MINUTE,
    *,
    sleep: Callable[[float], None] = time.sleep,
    monotonic: Callable[[], float] = time.monotonic,
) -> int:
    """Embed and upload chunks in batches, returning the number of persisted records."""
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    if max_estimated_tokens_per_minute < 1:
        raise ValueError("max_estimated_tokens_per_minute must be at least 1")
    if embedding_service.dimensions != EXPECTED_DIMENSIONS:
        raise ValueError(
            f"Embedding model is configured for {embedding_service.dimensions} dimensions, "
            f"but the Supabase schema expects {EXPECTED_DIMENSIONS}."
        )

    uploaded = 0
    next_request_at = 0.0
    for start in range(0, len(chunks), batch_size):
        batch = chunks[start : start + batch_size]
        wait_seconds = next_request_at - monotonic()
        if wait_seconds > 0:
            sleep(wait_seconds)
        request_started_at = monotonic()
        vectors = embedding_service.embed_texts([chunk["text"] for chunk in batch])
        records = [
            {**chunk, "embedding": vector}
            for chunk, vector in zip(batch, vectors, strict=True)
        ]
        uploaded += repository.upsert_chunks(records, batch_size=batch_size)
        print(f"Uploaded {uploaded}/{len(chunks)} chunks")
        estimated_tokens = sum(
            max(1, len(chunk["text"])) * ESTIMATED_TOKENS_PER_CHARACTER
            for chunk in batch
        )
        next_request_at = request_started_at + (
            estimated_tokens * 60 / max_estimated_tokens_per_minute
        )
    return uploaded


def main() -> int:
    """CLI entry point for the end-to-end chunk embedding and upload operation."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH, help="JSON chunk file")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Chunks per embedding/upload request",
    )
    parser.add_argument(
        "--max-estimated-tokens-per-minute",
        type=int,
        default=DEFAULT_MAX_ESTIMATED_TOKENS_PER_MINUTE,
        help="Target rate used to space requests (estimated conservatively from text length)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate the chunk file and report the work without calling Gemini or Supabase",
    )
    args = parser.parse_args()

    try:
        if args.batch_size < 1:
            raise ValueError("--batch-size must be at least 1")
        if args.max_estimated_tokens_per_minute < 1:
            raise ValueError("--max-estimated-tokens-per-minute must be at least 1")
        chunks = load_chunks(args.input)
        if args.dry_run:
            print(f"Dry run: {len(chunks)} valid chunks in {args.input.resolve()}")
            return 0
        if not chunks:
            print("No chunks to upload.")
            return 0

        embedding_service = EmbeddingService(batch_size=args.batch_size)
        repository = VectorRepository()
        uploaded = embed_and_upload(
            chunks,
            embedding_service,
            repository,
            args.batch_size,
            args.max_estimated_tokens_per_minute,
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError, RuntimeError, GeminiAPIError) as exc:
        if is_quota_exhausted(exc):
            print(
                "Embedding stopped: the Gemini API quota is exhausted. Check the Google AI Studio "
                "project, model limits, and billing, then rerun this command.",
                file=sys.stderr,
            )
        else:
            print(f"Embed/upload failed: {exc}", file=sys.stderr)
        return 1

    print(f"Successfully embedded and uploaded {uploaded} chunks to Supabase.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
