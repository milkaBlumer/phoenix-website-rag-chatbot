"""Clean scraped pages and split their text into overlapping retrieval chunks."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT_DIR = ROOT / "data" / "raw"
DEFAULT_OUTPUT_PATH = ROOT / "data" / "chunks" / "chunks.json"
DEFAULT_CHUNK_SIZE = 1_000
DEFAULT_CHUNK_OVERLAP = 150


@dataclass(frozen=True)
class Chunk:
    """A searchable text segment with source metadata."""

    chunk_id: str
    url: str
    title: str
    chunk_index: int
    text: str


def clean_text(text: str) -> str:
    """Normalize whitespace and remove empty lines while retaining paragraph boundaries."""
    paragraphs = [
        re.sub(r"\s+", " ", paragraph).strip()
        for paragraph in re.split(r"\n+", text)
    ]
    return "\n\n".join(paragraph for paragraph in paragraphs if paragraph)


def chunk_text(text: str, max_chars: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP) -> list[str]:
    """Split text at paragraph/sentence boundaries, with bounded character overlap."""
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1")
    if overlap < 0 or overlap >= max_chars:
        raise ValueError("overlap must be non-negative and smaller than max_chars")

    cleaned = clean_text(text)
    if not cleaned:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + max_chars, len(cleaned))
        if end < len(cleaned):
            window = cleaned[start:end]
            sentence_boundaries = [
                match.end()
                for match in re.finditer(r"(?<=[.!?؟。])\s+", window)
                if match.end() >= max_chars * 0.6
            ]
            paragraph_boundaries = [
                match.end()
                for match in re.finditer(r"\n\n", window)
                if match.end() >= max_chars * 0.6
            ]
            word_boundaries = [
                match.end()
                for match in re.finditer(r"\s+", window)
                if match.end() >= max_chars * 0.6
            ]
            boundary = max(paragraph_boundaries or sentence_boundaries or word_boundaries, default=0)
            if boundary:
                end = start + boundary

        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(cleaned):
            break

        next_start = end - overlap
        if next_start > start:
            while next_start < end and cleaned[next_start].isspace():
                next_start += 1
            if next_start < end and not cleaned[next_start - 1].isspace():
                whitespace = cleaned.rfind(" ", start, next_start)
                if whitespace > start:
                    next_start = whitespace + 1
        start = max(start + 1, next_start)

    return chunks


def _stable_chunk_id(url: str, index: int, text: str) -> str:
    """Create a deterministic ID so reprocessing identical source content is repeatable."""
    payload = f"{url}\0{index}\0{text}".encode()
    return hashlib.sha256(payload).hexdigest()


def chunks_from_page(page: dict[str, Any], max_chars: int, overlap: int) -> list[Chunk]:
    """Validate one scraper record and create indexed chunks for it."""
    url = page.get("url")
    text = page.get("text")
    title = page.get("title", "")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("Page is missing a non-empty 'url'")
    if not isinstance(text, str):
        raise TypeError(f"Page {url!r} is missing text content")
    if not isinstance(title, str):
        raise TypeError(f"Page {url!r} has a non-text title")

    chunks = chunk_text(text, max_chars=max_chars, overlap=overlap)
    return [
        Chunk(
            chunk_id=_stable_chunk_id(url, index, content),
            url=url,
            title=title.strip(),
            chunk_index=index,
            text=content,
        )
        for index, content in enumerate(chunks)
    ]


def load_pages(input_dir: Path) -> list[dict[str, Any]]:
    """Load JSON page records from a directory in deterministic filename order."""
    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory does not exist: {input_dir}")

    pages: list[dict[str, Any]] = []
    for path in sorted(input_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Could not read page JSON {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise TypeError(f"Expected a JSON object in {path}")
        pages.append(data)
    return pages


def process_pages(
    pages: list[dict[str, Any]], max_chars: int = DEFAULT_CHUNK_SIZE, overlap: int = DEFAULT_CHUNK_OVERLAP
) -> list[Chunk]:
    """Chunk each page, skipping empty-content pages."""
    chunks: list[Chunk] = []
    for page in pages:
        page_chunks = chunks_from_page(page, max_chars=max_chars, overlap=overlap)
        chunks.extend(page_chunks)
    return chunks


def write_chunks(chunks: list[Chunk], output_path: Path) -> None:
    """Serialize chunks to a UTF-8 JSON array, creating the destination directory."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([asdict(chunk) for chunk in chunks], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    """Read scraped pages, chunk them, and write the resulting JSON file."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_DIR, help="Directory of scraper JSON files")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output JSON file for chunks")
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE, help="Maximum chunk length in characters")
    parser.add_argument("--overlap", type=int, default=DEFAULT_CHUNK_OVERLAP, help="Overlap between chunks in characters")
    args = parser.parse_args()

    try:
        pages = load_pages(args.input)
        chunks = process_pages(pages, max_chars=args.chunk_size, overlap=args.overlap)
        write_chunks(chunks, args.output)
    except (FileNotFoundError, OSError, TypeError, ValueError) as exc:
        print(f"Chunking failed: {exc}", file=sys.stderr)
        return 1

    print(f"Created {len(chunks)} chunks from {len(pages)} pages: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
