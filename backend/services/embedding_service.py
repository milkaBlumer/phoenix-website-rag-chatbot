"""Generate Gemini vector embeddings for document chunks and search queries."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google import genai
from google.genai import types

from backend.check_setup import read_local_env
from backend.utils.retry import retry_transient

DEFAULT_MODEL = "gemini-embedding-001"
DEFAULT_OUTPUT_DIMENSIONALITY = 768
DEFAULT_BATCH_SIZE = 100
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_PATH = ROOT / "data" / "chunks" / "chunks.json"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "chunks" / "embedded_chunks.json"


@dataclass(frozen=True)
class EmbeddingSettings:
    """Embedding configuration loaded from environment variables and the project .env file."""

    api_key: str
    model: str = DEFAULT_MODEL
    output_dimensionality: int = DEFAULT_OUTPUT_DIMENSIONALITY

    @classmethod
    def from_env(cls) -> EmbeddingSettings:
        """Load and validate embedding configuration without exposing secret values."""
        file_values = read_local_env()
        api_key = os.environ.get("GEMINI_API_KEY") or file_values.get("GEMINI_API_KEY", "")
        model = (
            os.environ.get("GEMINI_EMBEDDING_MODEL")
            or file_values.get("GEMINI_EMBEDDING_MODEL")
            or DEFAULT_MODEL
        )
        raw_dimensions = (
            os.environ.get("EMBEDDING_DIMENSIONS")
            or file_values.get("EMBEDDING_DIMENSIONS")
            or str(DEFAULT_OUTPUT_DIMENSIONALITY)
        )
        if not api_key:
            raise ValueError("GEMINI_API_KEY is not configured. Set it in the environment or .env file.")
        try:
            dimensions = int(raw_dimensions)
        except ValueError as exc:
            raise ValueError("EMBEDDING_DIMENSIONS must be an integer.") from exc
        if dimensions < 1:
            raise ValueError("EMBEDDING_DIMENSIONS must be greater than zero.")
        return cls(api_key=api_key, model=model, output_dimensionality=dimensions)


class EmbeddingService:
    """Gemini embedding client with input validation and batch embedding support."""

    def __init__(
        self,
        client: Any | None = None,
        *,
        settings: EmbeddingSettings | None = None,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        self.settings = settings or EmbeddingSettings.from_env()
        self.client = client or genai.Client(api_key=self.settings.api_key)
        self.batch_size = batch_size

    @property
    def dimensions(self) -> int:
        """Number of values returned in each embedding vector."""
        return self.settings.output_dimensionality

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        """Return one embedding per input string, preserving order across batches."""
        if any(not isinstance(text, str) for text in texts):
            raise TypeError("Every embedding input must be a string.")
        if any(not text.strip() for text in texts):
            raise ValueError("Embedding inputs must not be empty or whitespace-only.")
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            response = retry_transient(self.client.models.embed_content)(
                model=self.settings.model,
                contents=batch,
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=self.settings.output_dimensionality,
                ),
            )
            embeddings = getattr(response, "embeddings", None)
            if not embeddings or len(embeddings) != len(batch):
                raise RuntimeError(
                    f"Gemini returned {len(embeddings or [])} embeddings for a batch of {len(batch)} texts."
                )
            for embedding in embeddings:
                values = getattr(embedding, "values", None)
                if values is None or len(values) != self.settings.output_dimensionality:
                    actual = len(values) if values is not None else 0
                    raise RuntimeError(
                        f"Gemini returned an embedding with {actual} dimensions; expected "
                        f"{self.settings.output_dimensionality}."
                    )
                vectors.append([float(value) for value in values])
        return vectors

    def embed_query(self, text: str) -> list[float]:
        """Embed a search query using Gemini's retrieval-query task type."""
        if not isinstance(text, str):
            raise TypeError("The query must be a string.")
        if not text.strip():
            raise ValueError("The query must not be empty or whitespace-only.")

        response = retry_transient(self.client.models.embed_content)(
            model=self.settings.model,
            contents=text,
            config=types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=self.settings.output_dimensionality,
            ),
        )
        embeddings = getattr(response, "embeddings", None)
        values = getattr(embeddings[0], "values", None) if embeddings else None
        if values is None or len(values) != self.settings.output_dimensionality:
            actual = len(values) if values is not None else 0
            raise RuntimeError(
                f"Gemini returned an embedding with {actual} dimensions; expected "
                f"{self.settings.output_dimensionality}."
            )
        return [float(value) for value in values]


def main() -> int:
    """Embed chunk JSON into a separate JSON file containing vectors and source metadata."""
    parser = argparse.ArgumentParser(description="Generate Gemini embeddings for a chunk JSON file.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_PATH, help="JSON array of chunks")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output JSON with embeddings")
    args = parser.parse_args()

    try:
        chunks = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(chunks, list):
            raise TypeError("Input must contain a JSON array of chunks.")
        if any(not isinstance(chunk, dict) or not isinstance(chunk.get("text"), str) for chunk in chunks):
            raise ValueError("Each chunk must be a JSON object with a text string.")
        if any(not chunk["text"].strip() for chunk in chunks):
            raise ValueError("Chunk text must not be empty or whitespace-only.")

        service = EmbeddingService()
        vectors = service.embed_texts([chunk["text"] for chunk in chunks])
        embedded_chunks = [
            {**chunk, "embedding": vector}
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(embedded_chunks, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError, RuntimeError) as exc:
        print(f"Embedding failed: {exc}", file=sys.stderr)
        return 1

    print(f"Generated {len(embedded_chunks)} {service.dimensions}-dimensional embeddings: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
