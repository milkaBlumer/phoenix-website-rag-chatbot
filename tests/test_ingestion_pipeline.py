from __future__ import annotations

from types import SimpleNamespace

from backend.ingestion import run as pipeline
from backend.ingestion.state import load_state, mark_page_synced, save_state


def _page(url: str, text: str = "תוכן לדוגמה") -> SimpleNamespace:
    return SimpleNamespace(url=url, title="דוגמה", text=text, fetched_at="2026-10-20T00:00:00+00:00")


def test_dry_run_reports_changes_without_services_or_state_writes(tmp_path, monkeypatch) -> None:
    sitemap_url = "https://example.com/sitemap.xml"
    page = _page("https://example.com/page")
    monkeypatch.setattr(pipeline, "discover_sitemap_urls", lambda _url: [page.url])
    monkeypatch.setattr(pipeline, "crawl_url_pages", lambda *_args, **_kwargs: iter([page]))

    result = pipeline.run_pipeline(
        sitemap_url=sitemap_url,
        state_path=tmp_path / "state.json",
        output_dir=tmp_path / "raw",
        dry_run=True,
    )

    assert result == {
        "discovered_pages": 1,
        "fetched_pages": 1,
        "changed_pages": 1,
        "chunks": 1,
        "complete_crawl": False,
    }
    assert not (tmp_path / "state.json").exists()


def test_pipeline_resumes_from_state_and_skips_unchanged_pages(tmp_path, monkeypatch) -> None:
    sitemap_url = "https://example.com/sitemap.xml"
    page = _page("https://example.com/page")
    monkeypatch.setattr(pipeline, "discover_sitemap_urls", lambda _url: [page.url])
    monkeypatch.setattr(pipeline, "crawl_url_pages", lambda *_args, **_kwargs: iter([page]))
    embedded_texts: list[str] = []
    synced_urls: list[str] = []
    embedding = SimpleNamespace(
        dimensions=768,
        embed_texts=lambda texts: (embedded_texts.extend(texts) or [[0.1] * 768 for _ in texts]),
    )
    repository = SimpleNamespace(
        EXPECTED_DIMENSIONS=768,
        sync_page_chunks=lambda url, records, batch_size: (synced_urls.append(url) or len(records)),
        delete_page=lambda _url: None,
    )
    state_path = tmp_path / "state.json"

    first = pipeline.run_pipeline(
        sitemap_url=sitemap_url,
        state_path=state_path,
        output_dir=tmp_path / "raw",
        embedding_service=embedding,
        repository=repository,
    )
    second = pipeline.run_pipeline(
        sitemap_url=sitemap_url,
        state_path=state_path,
        output_dir=tmp_path / "raw",
        embedding_service=embedding,
        repository=repository,
    )

    assert first["changed_pages"] == 1
    assert second["changed_pages"] == 0
    assert len(embedded_texts) == 1
    assert synced_urls == [page.url]
    assert page.url in load_state(state_path)["pages"]


def test_pipeline_keeps_checkpoint_when_crawl_stops_mid_run(tmp_path, monkeypatch) -> None:
    sitemap_url = "https://example.com/sitemap.xml"
    page = _page("https://example.com/first")

    def interrupted_pages(*_args, **_kwargs):
        yield page
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(pipeline, "discover_sitemap_urls", lambda _url: [page.url, "https://example.com/second"])
    monkeypatch.setattr(pipeline, "crawl_url_pages", interrupted_pages)
    embedding = SimpleNamespace(dimensions=768, embed_texts=lambda texts: [[0.1] * 768 for _ in texts])
    repository = SimpleNamespace(
        EXPECTED_DIMENSIONS=768,
        sync_page_chunks=lambda _url, records, batch_size: len(records),
    )
    state_path = tmp_path / "state.json"

    try:
        pipeline.run_pipeline(
            sitemap_url=sitemap_url,
            state_path=state_path,
            output_dir=tmp_path / "raw",
            full=True,
            embedding_service=embedding,
            repository=repository,
        )
    except RuntimeError as error:
        assert str(error) == "simulated interruption"
    else:
        raise AssertionError("Expected simulated interruption")

    assert page.url in load_state(state_path)["pages"]


def test_full_sync_deletes_removed_pages_after_complete_crawl(tmp_path, monkeypatch) -> None:
    sitemap_url = "https://example.com/sitemap.xml"
    page = _page("https://example.com/current")
    old_page = {"url": "https://example.com/removed", "title": "ישן", "text": "ישן"}
    state_path = tmp_path / "state.json"
    state = load_state(state_path)
    mark_page_synced(old_page, state)
    save_state(state_path, state)
    monkeypatch.setattr(pipeline, "discover_sitemap_urls", lambda _url: [page.url])
    monkeypatch.setattr(pipeline, "crawl_url_pages", lambda *_args, **_kwargs: iter([page]))
    deleted: list[str] = []
    embedding = SimpleNamespace(dimensions=768, embed_texts=lambda texts: [[0.1] * 768 for _ in texts])
    repository = SimpleNamespace(
        EXPECTED_DIMENSIONS=768,
        sync_page_chunks=lambda _url, records, batch_size: len(records),
        delete_page=deleted.append,
    )

    result = pipeline.run_pipeline(
        sitemap_url=sitemap_url,
        state_path=state_path,
        output_dir=tmp_path / "raw",
        full=True,
        embedding_service=embedding,
        repository=repository,
    )

    assert result["complete_crawl"] is True
    assert deleted == [old_page["url"]]
    assert old_page["url"] not in load_state(state_path)["pages"]


def test_incomplete_full_crawl_does_not_delete_pages(tmp_path, monkeypatch) -> None:
    sitemap_url = "https://example.com/sitemap.xml"
    page = _page("https://example.com/current")
    old_page = {"url": "https://example.com/removed", "title": "ישן", "text": "ישן"}
    state_path = tmp_path / "state.json"
    state = load_state(state_path)
    mark_page_synced(old_page, state)
    save_state(state_path, state)
    monkeypatch.setattr(pipeline, "discover_sitemap_urls", lambda _url: [page.url, "https://example.com/missed"])
    monkeypatch.setattr(pipeline, "crawl_url_pages", lambda *_args, **_kwargs: iter([page]))
    deleted: list[str] = []
    embedding = SimpleNamespace(dimensions=768, embed_texts=lambda texts: [[0.1] * 768 for _ in texts])
    repository = SimpleNamespace(
        EXPECTED_DIMENSIONS=768,
        sync_page_chunks=lambda _url, records, batch_size: len(records),
        delete_page=deleted.append,
    )

    result = pipeline.run_pipeline(
        sitemap_url=sitemap_url,
        state_path=state_path,
        output_dir=tmp_path / "raw",
        full=True,
        embedding_service=embedding,
        repository=repository,
    )

    assert result["complete_crawl"] is False
    assert deleted == []
    assert old_page["url"] in load_state(state_path)["pages"]
