from __future__ import annotations

import gzip
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from requests import Response
from urllib3.response import HTTPResponse

from backend.ingestion.scraper import discover_sitemap_urls


def _response(content: bytes) -> SimpleNamespace:
    return SimpleNamespace(
        headers={},
        raw=SimpleNamespace(read=lambda _limit: content),
        raise_for_status=lambda: None,
        close=lambda: None,
    )


def test_discovers_same_host_pages_from_sitemap_index() -> None:
    index = b"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <sitemap><loc>https://example.com/pages.xml</loc></sitemap>
      <sitemap><loc>https://external.example/pages.xml</loc></sitemap>
    </sitemapindex>"""
    pages = b"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://example.com/a</loc></url>
      <url><loc>https://example.com/b#section</loc></url>
      <url><loc>https://external.example/c</loc></url>
    </urlset>"""
    session = Mock()
    session.get.side_effect = [_response(index), _response(pages)]

    result = discover_sitemap_urls("https://example.com/sitemap.xml", session=session)

    assert result == ["https://example.com/a", "https://example.com/b"]
    assert session.get.call_count == 2


def test_rejects_invalid_sitemap_xml() -> None:
    session = Mock()
    session.get.return_value = _response(b"<urlset>")

    with pytest.raises(ValueError, match="Invalid XML sitemap"):
        discover_sitemap_urls("https://example.com/sitemap.xml", session=session)


def test_limits_sitemap_tree_size() -> None:
    first = b"<sitemapindex><sitemap><loc>https://example.com/second.xml</loc></sitemap></sitemapindex>"
    session = Mock()
    session.get.return_value = _response(first)

    with pytest.raises(ValueError, match="exceeds the limit"):
        discover_sitemap_urls(
            "https://example.com/first.xml",
            session=session,
            max_sitemaps=1,
        )


def test_reads_gzip_encoded_sitemap() -> None:
    xml = b"<urlset><url><loc>https://example.com/page</loc></url></urlset>"
    response = Response()
    response.status_code = 200
    response.url = "https://example.com/sitemap.xml"
    response.headers["Content-Encoding"] = "gzip"
    response.raw = HTTPResponse(
        body=BytesIO(gzip.compress(xml)),
        headers={"Content-Encoding": "gzip"},
        preload_content=False,
    )
    session = Mock()
    session.get.return_value = response

    result = discover_sitemap_urls("https://example.com/sitemap.xml", session=session)

    assert result == ["https://example.com/page"]
