"""Run a resumable sitemap-to-Supabase ingestion pipeline."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

from backend.check_setup import read_local_env
from backend.ingestion.chunker import chunks_from_page
from backend.ingestion.scraper import (
    DEFAULT_OUTPUT_DIR,
    MAX_PAGES,
    ScrapedPage,
    crawl_url_pages,
    discover_sitemap_urls,
    normalize_url,
)
from backend.ingestion.state import changed_pages, load_state, mark_page_synced, save_state
from backend.utils.structured_logging import configure_logging

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_PATH = ROOT / "data" / "state" / "ingestion.json"
DEFAULT_CHUNK_SIZE = 1_000
DEFAULT_CHUNK_OVERLAP = 150
DEFAULT_BATCH_SIZE = 100
logger = logging.getLogger("backend.ingestion")


def resolve_sitemap_url(source_url: str, sitemap_url: str | None = None) -> str:
    """Resolve explicit sitemap URL or default to /sitemap.xml on SOURCE_URL's host."""
    if sitemap_url:
        return sitemap_url
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("SOURCE_URL must be a valid HTTP(S) URL.")
    return urlunparse((parsed.scheme, parsed.netloc, "/sitemap.xml", "", "", ""))


def pages_as_records(pages: list[ScrapedPage]) -> list[dict[str, Any]]:
    """Convert scraper dataclasses to plain records used by chunking and state."""
    return [
        {"url": page.url, "title": page.title, "text": page.text, "fetched_at": page.fetched_at}
        for page in pages
    ]


def run_pipeline(
    *,
    sitemap_url: str,
    state_path: Path = DEFAULT_STATE_PATH,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    max_pages: int | None = MAX_PAGES,
    full: bool = False,
    dry_run: bool = False,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    batch_size: int = DEFAULT_BATCH_SIZE,
    embedding_service: Any | None = None,
    repository: Any | None = None,
) -> dict[str, int | bool]:
    """Fetch and sync pages incrementally, checkpointing each successful page."""
    if not full and (max_pages is None or max_pages < 1):
        raise ValueError("max_pages must be at least 1 unless full=True")
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")

    sitemap_urls = discover_sitemap_urls(sitemap_url)
    selected_urls = sitemap_urls if full else sitemap_urls[:max_pages]
    if not selected_urls:
        raise RuntimeError("The sitemap contains no same-host pages to crawl.")

    state = load_state(state_path)
    allowed_host = urlparse(sitemap_url).hostname or ""
    fetched_urls: set[str] = set()
    fetched_pages = 0
    changed_count = 0
    total_chunks = 0

    for scraped_page in crawl_url_pages(
        selected_urls,
        allowed_host=allowed_host,
        limit=None,
        output_dir=output_dir,
    ):
        page = pages_as_records([scraped_page])[0]
        page_url = page["url"]
        fetched_urls.add(normalize_url(page_url))
        fetched_pages += 1
        if not changed_pages([page], state):
            continue

        chunks = chunks_from_page(page, max_chars=chunk_size, overlap=chunk_overlap)
        total_chunks += len(chunks)
        changed_count += 1
        if dry_run:
            continue

        if repository is None:
            from backend.repositories.vector_repository import VectorRepository

            repository = VectorRepository()
        records: list[dict[str, Any]] = []
        if chunks:
            if embedding_service is None:
                from backend.services.embedding_service import EmbeddingService

                embedding_service = EmbeddingService(batch_size=batch_size)
            expected_dimensions = getattr(repository, "EXPECTED_DIMENSIONS", 768)
            if embedding_service.dimensions != expected_dimensions:
                raise ValueError(
                    f"Embedding model has {embedding_service.dimensions} dimensions, "
                    f"but database schema expects {expected_dimensions}."
                )
            vectors = embedding_service.embed_texts([chunk.text for chunk in chunks])
            records = [
                {
                    "chunk_id": chunk.chunk_id,
                    "url": chunk.url,
                    "title": chunk.title,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "embedding": vector,
                }
                for chunk, vector in zip(chunks, vectors, strict=True)
            ]

        repository.sync_page_chunks(page_url, records, batch_size=batch_size)
        mark_page_synced(page, state)
        save_state(state_path, state)
        logger.info(
            "ingestion_page_synced",
            extra={"event": "ingestion_page_synced", "pages": 1, "chunks": len(records)},
        )

    complete_crawl = full and fetched_urls == {normalize_url(url) for url in selected_urls}
    if dry_run:
        return {
            "discovered_pages": len(sitemap_urls),
            "fetched_pages": fetched_pages,
            "changed_pages": changed_count,
            "chunks": total_chunks,
            "complete_crawl": complete_crawl,
        }

    if complete_crawl:
        current_urls = {normalize_url(url) for url in selected_urls}
        removed_urls = {
            url for url in state["pages"] if normalize_url(url) not in current_urls
        }
        if removed_urls and repository is None:
            from backend.repositories.vector_repository import VectorRepository

            repository = VectorRepository()
        for url in sorted(removed_urls):
            assert repository is not None
            repository.delete_page(url)
            del state["pages"][url]
        if removed_urls:
            save_state(state_path, state)
            logger.info(
                "ingestion_removed_pages",
                extra={"event": "ingestion_removed_pages", "pages": len(removed_urls)},
            )

    return {
        "discovered_pages": len(sitemap_urls),
        "fetched_pages": fetched_pages,
        "changed_pages": changed_count,
        "chunks": total_chunks,
        "complete_crawl": complete_crawl,
    }


def main() -> int:
    """CLI entry point for dry runs, limited syncs, and full sitemap syncs."""
    configure_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-url", help="Website URL; defaults to SOURCE_URL in .env")
    parser.add_argument("--sitemap-url", help="Sitemap URL; defaults to SOURCE_URL host + /sitemap.xml")
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES, help="Pages to fetch unless --full is set")
    parser.add_argument("--full", action="store_true", help="Crawl the whole sitemap and sync removed pages")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and report changes without API calls or state writes",
    )
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_PATH, help="Resume-state JSON path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR, help="Raw page JSON output directory")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--overlap", type=int, default=DEFAULT_CHUNK_OVERLAP)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()

    local_env = read_local_env()
    source_url = args.source_url or os.environ.get("SOURCE_URL") or local_env.get("SOURCE_URL")
    if not source_url and not args.sitemap_url:
        parser.error("Provide --source-url/--sitemap-url or configure SOURCE_URL in .env")

    try:
        sitemap_url = resolve_sitemap_url(source_url or args.sitemap_url or "", args.sitemap_url)
        result = run_pipeline(
            sitemap_url=sitemap_url,
            state_path=args.state_file,
            output_dir=args.output,
            max_pages=args.max_pages,
            full=args.full,
            dry_run=args.dry_run,
            chunk_size=args.chunk_size,
            chunk_overlap=args.overlap,
            batch_size=args.batch_size,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        logger.error(
            "ingestion_pipeline_failed",
            extra={"event": "ingestion_pipeline_failed", "error_type": type(exc).__name__},
        )
        print(f"Pipeline failed: {exc}", file=sys.stderr)
        return 1

    mode = "Dry run" if args.dry_run else "Pipeline complete"
    logger.info(
        "ingestion_pipeline_complete",
        extra={
            "event": "ingestion_pipeline_complete",
            "pages": result["fetched_pages"],
            "changed_pages": result["changed_pages"],
            "chunks": result["chunks"],
        },
    )
    print(
        f"{mode}: {result['fetched_pages']}/{result['discovered_pages']} pages fetched, "
        f"{result['changed_pages']} changed, {result['chunks']} chunks; "
        f"complete crawl={result['complete_crawl']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
