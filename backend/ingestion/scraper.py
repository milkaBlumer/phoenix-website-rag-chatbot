"""Fetch a small set of pages from a website and save their main text locally."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup
from requests import Response

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_DIR = ROOT / "data" / "raw"
USER_AGENT = "HebrewRAGResearchBot/0.1 (+educational-purpose; contact: project-owner)"
REQUEST_TIMEOUT_SECONDS = 20
REQUEST_DELAY_SECONDS = 1.0
MAX_PAGES = 5
MAX_PAGE_BYTES = 5_000_000


@dataclass(frozen=True)
class ScrapedPage:
    """A successfully fetched HTML page with its primary readable content."""

    url: str
    title: str
    text: str
    fetched_at: str


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication and remove fragments and common tracking params."""
    url, _fragment = urldefrag(url.strip())
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Expected an absolute HTTP(S) URL, got: {url!r}")
    hostname = parsed.hostname.lower()
    netloc = hostname if parsed.port is None else f"{hostname}:{parsed.port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    return urlunparse((parsed.scheme.lower(), netloc, path, "", "", ""))


def allowed_by_robots(url: str, user_agent: str = USER_AGENT) -> bool:
    """Check robots.txt permissions for the given URL."""
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    parser = RobotFileParser()
    parser.set_url(robots_url)
    try:
        response = requests.get(
            robots_url,
            headers={"User-Agent": user_agent},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        if response.status_code == 404:
            return True
        response.raise_for_status()
        parser.parse(response.text.splitlines())
    except requests.RequestException:
        # Fail closed: don't crawl a host if its crawl policy cannot be checked.
        return False
    return parser.can_fetch(user_agent, url)


def _fetch_sitemap_xml(session: requests.Session, sitemap_url: str) -> bytes:
    """Fetch an XML sitemap with the same bounds and timeout as page requests."""
    response = session.get(
        sitemap_url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_SECONDS,
        stream=True,
    )
    try:
        response.raise_for_status()
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_PAGE_BYTES:
            raise ValueError(f"Sitemap is larger than {MAX_PAGE_BYTES} bytes: {sitemap_url}")
        response.raw.decode_content = True
        content = response.raw.read(MAX_PAGE_BYTES + 1)
        if len(content) > MAX_PAGE_BYTES:
            raise ValueError(f"Sitemap is larger than {MAX_PAGE_BYTES} bytes: {sitemap_url}")
        return content
    finally:
        response.close()


def discover_sitemap_urls(
    sitemap_url: str,
    *,
    session: requests.Session | None = None,
    allowed_host: str | None = None,
    max_sitemaps: int = 100,
) -> list[str]:
    """Read sitemap URL sets and indexes, returning unique HTTP(S) page URLs.

    Nested sitemap indexes and page URLs are restricted to the configured host.
    ``max_sitemaps`` prevents unexpectedly large or cyclic sitemap trees.
    """
    if max_sitemaps < 1:
        raise ValueError("max_sitemaps must be at least 1")
    sitemap_url = normalize_url(sitemap_url)
    root_host = allowed_host or urlparse(sitemap_url).hostname
    client = session or requests.Session()
    own_session = session is None
    queue = [sitemap_url]
    visited_sitemaps: set[str] = set()
    page_urls: list[str] = []

    try:
        while queue:
            current_sitemap = queue.pop(0)
            if current_sitemap in visited_sitemaps:
                continue
            if len(visited_sitemaps) >= max_sitemaps:
                raise ValueError(f"Sitemap tree exceeds the limit of {max_sitemaps} files")
            if urlparse(current_sitemap).hostname != root_host:
                continue
            visited_sitemaps.add(current_sitemap)
            try:
                root = ElementTree.fromstring(_fetch_sitemap_xml(client, current_sitemap))
            except ElementTree.ParseError as exc:
                raise ValueError(f"Invalid XML sitemap: {current_sitemap}") from exc

            root_name = root.tag.rsplit("}", maxsplit=1)[-1].lower()
            if root_name not in {"urlset", "sitemapindex"}:
                raise ValueError(f"Unsupported sitemap XML root <{root_name}> at {current_sitemap}")
            for location in root.findall(".//{*}loc"):
                if not location.text:
                    continue
                try:
                    candidate = normalize_url(urljoin(current_sitemap, location.text.strip()))
                except ValueError:
                    continue
                if urlparse(candidate).hostname != root_host:
                    continue
                if root_name == "sitemapindex":
                    if candidate not in visited_sitemaps and candidate not in queue:
                        queue.append(candidate)
                elif candidate not in page_urls:
                    page_urls.append(candidate)
    finally:
        if own_session:
            client.close()
    return page_urls


def extract_page(response: Response) -> ScrapedPage:
    """Extract title and readable body text, excluding navigation and boilerplate."""
    soup = BeautifulSoup(response.content, "html.parser")
    for element in soup.select(
        "script, style, noscript, svg, iframe, nav, header, footer, aside, form, "
        "[role='navigation'], [aria-hidden='true']"
    ):
        element.decompose()

    main = soup.find("main") or soup.find("article") or soup.body or soup
    title = " ".join(soup.title.get_text(" ", strip=True).split()) if soup.title else ""
    text = "\n".join(
        line for line in (" ".join(s.split()) for s in main.get_text("\n").splitlines()) if line
    )
    if not text:
        raise ValueError(f"No readable text found at {response.url}")

    return ScrapedPage(
        url=response.url,
        title=title,
        text=text,
        fetched_at=datetime.now(UTC).isoformat(),
    )


def discover_links(page: ScrapedPage, html: str, allowed_host: str) -> list[str]:
    """Return same-host links from HTML in document order."""
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href", "").strip()
        if not href or href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        try:
            candidate = normalize_url(urljoin(page.url, href))
        except ValueError:
            continue
        parsed = urlparse(candidate)
        if parsed.hostname == allowed_host and parsed.path.lower().endswith(
            (".pdf", ".jpg", ".jpeg", ".png", ".zip", ".doc", ".docx")
        ):
            continue
        if parsed.hostname == allowed_host:
            links.append(candidate)
    return list(dict.fromkeys(links))


def fetch_page_and_links(
    session: requests.Session, url: str, allowed_host: str
) -> tuple[ScrapedPage, list[str]]:
    """Fetch a page once and return both extracted content and its in-scope links."""
    response = session.get(
        url,
        headers={"User-Agent": USER_AGENT},
        timeout=REQUEST_TIMEOUT_SECONDS,
        stream=True,
    )
    try:
        response.raise_for_status()
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
            raise ValueError(f"Skipping non-HTML content at {url} ({content_type or 'unknown type'})")
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_PAGE_BYTES:
            raise ValueError(f"Page is larger than {MAX_PAGE_BYTES} bytes: {url}")
        response.raw.decode_content = True
        content = response.raw.read(MAX_PAGE_BYTES + 1)
        if len(content) > MAX_PAGE_BYTES:
            raise ValueError(f"Page is larger than {MAX_PAGE_BYTES} bytes: {url}")
        response._content = content
        if urlparse(response.url).hostname != allowed_host:
            raise ValueError(f"Redirected outside the configured host: {response.url}")
        page = extract_page(response)
        links = discover_links(page, content.decode(response.encoding or "utf-8", errors="replace"), allowed_host)
        return page, links
    finally:
        response.close()


def save_pages(pages: list[ScrapedPage], output_dir: Path) -> list[Path]:
    """Write pages as individual JSON files, using a stable URL-derived filename."""
    output_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for page in pages:
        digest = hashlib.sha256(page.url.encode("utf-8")).hexdigest()[:16]
        path = output_dir / f"{digest}.json"
        path.write_text(
            json.dumps(asdict(page), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        saved.append(path)
    return saved


def crawl_url_pages(
    urls: list[str],
    *,
    allowed_host: str,
    limit: int | None = MAX_PAGES,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> Iterator[ScrapedPage]:
    """Yield pages as they are fetched so long crawls can be processed incrementally."""
    if limit is not None and limit < 1:
        raise ValueError("Page limit must be at least 1")
    urls = list(dict.fromkeys(normalize_url(url) for url in urls))
    if not allowed_host:
        raise ValueError("The start URL must include a hostname")

    session = requests.Session()
    fetched = 0
    try:
        for url in urls:
            if limit is not None and fetched >= limit:
                break
            if urlparse(url).hostname != allowed_host:
                continue
            if not allowed_by_robots(url):
                print(f"SKIP robots.txt disallows or is unreachable: {url}", file=sys.stderr)
                continue

            try:
                page, _links = fetch_page_and_links(session, url, allowed_host)
            except (requests.RequestException, ValueError) as exc:
                print(f"SKIP {url}: {exc}", file=sys.stderr)
                continue

            save_pages([page], output_dir)
            fetched += 1
            yield page
            if limit is None or fetched < limit:
                time.sleep(REQUEST_DELAY_SECONDS)
    finally:
        session.close()

    if not fetched:
        raise RuntimeError("No pages were scraped. Check the URL, network access, and robots.txt.")


def crawl_urls(
    urls: list[str],
    *,
    allowed_host: str,
    limit: int | None = MAX_PAGES,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> list[ScrapedPage]:
    """Fetch a supplied list of same-host pages, respecting robots.txt and throttling."""
    return list(crawl_url_pages(urls, allowed_host=allowed_host, limit=limit, output_dir=output_dir))


def crawl(
    start_url: str,
    limit: int | None = MAX_PAGES,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> list[ScrapedPage]:
    """Breadth-first crawl of same-host links, respecting robots.txt."""
    start_url = normalize_url(start_url)
    allowed_host = urlparse(start_url).hostname
    if not allowed_host:
        raise ValueError("The start URL must include a hostname")

    session = requests.Session()
    queue = [start_url]
    visited: set[str] = set()
    pages: list[ScrapedPage] = []
    try:
        while queue and (limit is None or len(pages) < limit):
            url = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            if urlparse(url).hostname != allowed_host:
                continue
            if not allowed_by_robots(url):
                print(f"SKIP robots.txt disallows or is unreachable: {url}", file=sys.stderr)
                continue
            try:
                page, links = fetch_page_and_links(session, url, allowed_host)
            except (requests.RequestException, ValueError) as exc:
                print(f"SKIP {url}: {exc}", file=sys.stderr)
                continue
            pages.append(page)
            for link in links:
                if link not in visited and link not in queue:
                    queue.append(link)
            if queue and (limit is None or len(pages) < limit):
                time.sleep(REQUEST_DELAY_SECONDS)
    finally:
        session.close()

    if not pages:
        raise RuntimeError("No pages were scraped. Check the URL, network access, and robots.txt.")
    save_pages(pages, output_dir)
    return pages


def crawl_sitemap(
    sitemap_url: str,
    limit: int | None = MAX_PAGES,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> list[ScrapedPage]:
    """Crawl URLs from a sitemap or sitemap index, optionally limiting page count."""
    sitemap_url = normalize_url(sitemap_url)
    allowed_host = urlparse(sitemap_url).hostname
    if not allowed_host:
        raise ValueError("The sitemap URL must include a hostname")
    urls = discover_sitemap_urls(sitemap_url, allowed_host=allowed_host)
    if not urls:
        raise RuntimeError(f"No same-host page URLs were found in sitemap {sitemap_url}")
    return crawl_urls(urls, allowed_host=allowed_host, limit=limit, output_dir=output_dir)


def main() -> int:
    """CLI entry point for either a link crawl or a sitemap crawl."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?", help="Start page/sitemap URL; defaults to SOURCE_URL from .env")
    parser.add_argument("--sitemap", action="store_true", help="Treat the URL as an XML sitemap or sitemap index")
    parser.add_argument("--all", action="store_true", help="Crawl every same-host URL discovered in the sitemap")
    parser.add_argument("--limit", type=int, default=MAX_PAGES, help="Maximum pages (default: 5; ignored with --all)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_DIR, help="Directory for page JSON files")
    args = parser.parse_args()

    from backend.check_setup import read_local_env

    url = args.url or os.environ.get("SOURCE_URL") or read_local_env().get("SOURCE_URL")
    if not url:
        parser.error("Provide a start URL or configure SOURCE_URL in .env")

    try:
        limit = None if args.all else args.limit
        pages = (
            crawl_sitemap(url, limit=limit, output_dir=args.output)
            if args.sitemap or args.all
            else crawl(url, limit=limit, output_dir=args.output)
        )
    except (requests.RequestException, RuntimeError, ValueError) as exc:
        print(f"Scrape failed: {exc}", file=sys.stderr)
        return 1

    print(f"Saved {len(pages)} pages to {args.output.resolve()}")
    for page in pages:
        print(f"- {page.title or '(untitled)'} — {page.url}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
