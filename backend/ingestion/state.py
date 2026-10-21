"""Persistent, atomic state for resumable ingestion runs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATE_VERSION = 1


def page_fingerprint(page: dict[str, Any]) -> str:
    """Hash the URL and extracted page content to detect changes reliably."""
    payload = json.dumps(
        {"url": page.get("url"), "title": page.get("title", ""), "text": page.get("text", "")},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def load_state(path: Path) -> dict[str, Any]:
    """Load the URL-to-fingerprint state file, returning an empty state if absent."""
    if not path.exists():
        return {"version": STATE_VERSION, "pages": {}}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read ingestion state {path}: {exc}") from exc
    if not isinstance(state, dict) or state.get("version") != STATE_VERSION:
        raise ValueError(f"Unsupported ingestion state format in {path}")
    if not isinstance(state.get("pages"), dict):
        raise TypeError(f"Invalid pages map in ingestion state {path}")
    return state


def save_state(path: Path, state: dict[str, Any]) -> None:
    """Atomically persist state so interruption cannot leave a partial JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = datetime.now(UTC).isoformat()
    descriptor, temporary_name = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(state, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary_name).replace(path)
    except Exception:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def changed_pages(pages: list[dict[str, Any]], state: dict[str, Any]) -> list[dict[str, Any]]:
    """Select pages whose current extracted content differs from the synced state."""
    known = state["pages"]
    return [page for page in pages if known.get(page.get("url"), {}).get("fingerprint") != page_fingerprint(page)]


def mark_page_synced(page: dict[str, Any], state: dict[str, Any]) -> None:
    """Record a page only after its chunks have been successfully handled."""
    state["pages"][page["url"]] = {
        "fingerprint": page_fingerprint(page),
        "synced_at": datetime.now(UTC).isoformat(),
    }
