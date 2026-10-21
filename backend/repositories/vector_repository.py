"""Supabase repository for storing and retrieving embedded document chunks."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from backend.check_setup import read_local_env
from backend.utils.retry import retry_transient
from supabase import Client, create_client

TABLE_NAME = "documents"
MATCH_FUNCTION = "match_documents"
EXPECTED_DIMENSIONS = 768
DEFAULT_MATCH_COUNT = 5
UPSERT_BATCH_SIZE = 100


@dataclass(frozen=True)
class SupabaseSettings:
    """Supabase connection settings loaded from the environment or local .env file."""

    url: str
    key: str

    @classmethod
    def from_env(cls) -> SupabaseSettings:
        """Load and validate the Supabase URL and key without printing the key."""
        local_env = read_local_env()
        url = os.environ.get("SUPABASE_URL") or local_env.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_KEY") or local_env.get("SUPABASE_KEY", "")
        missing = [name for name, value in (("SUPABASE_URL", url), ("SUPABASE_KEY", key)) if not value]
        if missing:
            raise ValueError(f"Missing Supabase configuration: {', '.join(missing)}")
        if not url.startswith(("https://", "http://")):
            raise ValueError("SUPABASE_URL must be an HTTP(S) URL.")
        return cls(url=url.rstrip("/"), key=key)


class VectorRepository:
    """Small data-access layer around Supabase document upserts and vector search."""

    def __init__(self, client: Any | None = None, *, settings: SupabaseSettings | None = None) -> None:
        if client is None:
            resolved_settings = settings or SupabaseSettings.from_env()
            client = create_client(resolved_settings.url, resolved_settings.key)
        self.client: Client = client

    @staticmethod
    def _validate_record(record: dict[str, Any]) -> dict[str, Any]:
        """Validate a chunk+embedding record and map it to the database schema."""
        required = ("chunk_id", "url", "text", "embedding")
        missing = [key for key in required if key not in record]
        if missing:
            raise ValueError(f"Record is missing required fields: {', '.join(missing)}")

        chunk_id = record["chunk_id"]
        url = record["url"]
        content = record["text"]
        embedding = record["embedding"]
        title = record.get("title", "")
        chunk_index = record.get("chunk_index", 0)
        if not isinstance(chunk_id, str) or not chunk_id:
            raise ValueError("chunk_id must be a non-empty string.")
        if not isinstance(url, str) or not url:
            raise ValueError("url must be a non-empty string.")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("text must be a non-empty string.")
        if not isinstance(title, str):
            raise TypeError("title must be a string.")
        if isinstance(chunk_index, bool) or not isinstance(chunk_index, int) or chunk_index < 0:
            raise ValueError("chunk_index must be a non-negative integer.")
        if not isinstance(embedding, (list, tuple)):
            raise TypeError("embedding must be a list or tuple of numbers.")
        if len(embedding) != EXPECTED_DIMENSIONS:
            raise ValueError(f"embedding must have {EXPECTED_DIMENSIONS} dimensions, got {len(embedding)}.")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in embedding):
            raise TypeError("embedding values must be numbers.")

        return {
            "id": chunk_id,
            "url": url,
            "title": title,
            "chunk_index": chunk_index,
            "content": content,
            "embedding": [float(value) for value in embedding],
        }

    def upsert_chunks(self, records: list[dict[str, Any]], batch_size: int = UPSERT_BATCH_SIZE) -> int:
        """Upsert validated chunks in batches and return the total saved record count."""
        if batch_size < 1:
            raise ValueError("batch_size must be at least 1")
        if not records:
            return 0
        rows = [self._validate_record(record) for record in records]
        for start in range(0, len(rows), batch_size):
            retry_transient(
                self.client.table(TABLE_NAME).upsert(
                    rows[start : start + batch_size],
                    on_conflict="id",
                ).execute
            )()
        return len(rows)

    def sync_page_chunks(
        self,
        url: str,
        records: list[dict[str, Any]],
        batch_size: int = UPSERT_BATCH_SIZE,
    ) -> int:
        """Upsert a page's current chunks, then remove older chunks for that page."""
        if any(record.get("url") != url for record in records):
            raise ValueError("Every chunk must belong to the page URL being synchronized.")
        saved = self.upsert_chunks(records, batch_size=batch_size)
        existing_ids = [record["chunk_id"] for record in records]
        query = self.client.table(TABLE_NAME).delete().eq("url", url)
        if existing_ids:
            query = query.not_.in_("id", existing_ids)
        retry_transient(query.execute)()
        return saved

    def delete_page(self, url: str) -> None:
        """Remove all stored chunks for a page that is no longer in the source sitemap."""
        query = self.client.table(TABLE_NAME).delete().eq("url", url)
        retry_transient(query.execute)()

    def search(self, embedding: list[float], limit: int = DEFAULT_MATCH_COUNT) -> list[dict[str, Any]]:
        """Return the nearest chunks ranked by cosine similarity using the SQL RPC."""
        if len(embedding) != EXPECTED_DIMENSIONS:
            raise ValueError(f"query embedding must have {EXPECTED_DIMENSIONS} dimensions.")
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in embedding):
            raise TypeError("query embedding values must be numbers.")
        if limit < 1:
            raise ValueError("limit must be at least 1")
        response = retry_transient(
            self.client.rpc(
                MATCH_FUNCTION,
                {
                    "query_embedding": [float(value) for value in embedding],
                    "match_count": limit,
                },
            ).execute
        )()
        return list(response.data or [])
