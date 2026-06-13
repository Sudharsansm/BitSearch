"""
``bie.map()`` — discover a website's structure before crawling it.

This implements the "Map" primitive: given a site's root URL, find its
sitemap(s) (via ``robots.txt`` and common conventions) and return the
list of URLs it advertises — useful for deciding what to crawl/extract
without having to crawl the whole site first.

This is a real, standards-based implementation (sitemap.xml / sitemap
index parsing per the sitemaps.org protocol + robots.txt ``Sitemap:``
directives). It does **not** attempt to "discover architecture" via
crawling — for that, use :func:`bie.crawl_site` and inspect the returned
documents' URLs.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import httpx
from selectolax.parser import HTMLParser

logger = logging.getLogger("bie.sitemap")

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 BIE/0.5"
)

_COMMON_SITEMAP_PATHS = ("/sitemap.xml", "/sitemap_index.xml")

_SITEMAP_RE = re.compile(r"^Sitemap:\s*(\S+)", re.I | re.M)


@dataclass
class SiteMap:
    """Result of :func:`map_site`."""

    root: str
    sitemap_urls: list[str] = field(default_factory=list)
    urls: list[str] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.urls)

    def __str__(self) -> str:  # pragma: no cover - convenience only
        return (
            f"<SiteMap root={self.root!r} "
            f"sitemaps={len(self.sitemap_urls)} urls={len(self.urls)}>"
        )

    def filter(self, pattern: str) -> list[str]:
        """Return the subset of discovered URLs matching a regex
        ``pattern`` (e.g. ``r"/blog/"``)."""
        regex = re.compile(pattern)
        return [u for u in self.urls if regex.search(u)]


def map_site(
    url: str,
    max_sitemaps: int = 20,
    max_urls: int = 5000,
    timeout: float = 15.0,
) -> SiteMap:
    """Discover the sitemap(s) and listed URLs for the site containing ``url``.

    Lookup order:
      1. Fetch ``robots.txt`` and read any ``Sitemap:`` directives.
      2. If none found, try common conventional paths
         (``/sitemap.xml``, ``/sitemap_index.xml``).
      3. Recursively expand sitemap indexes (a sitemap that itself lists
         other sitemaps) up to ``max_sitemaps`` total files.

    Args:
        url: Any URL on the target site — only its scheme+host is used.
        max_sitemaps: Maximum number of sitemap XML files to fetch
            (guards against pathological sitemap indexes).
        max_urls: Maximum number of page URLs to collect.
        timeout: Per-request timeout in seconds.

    Returns:
        A :class:`SiteMap` with the discovered sitemap files and page URLs.
        If no sitemap can be found, ``sitemap_urls`` and ``urls`` are
        empty — this is common and not an error; fall back to
        :func:`bie.crawl_site` for link-based discovery instead.
    """
    parsed = urlparse(url)
    root = f"{parsed.scheme}://{parsed.netloc}"

    headers = {"User-Agent": _USER_AGENT}
    site_map = SiteMap(root=root)

    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        candidates = _sitemaps_from_robots(client, root)
        if not candidates:
            candidates = [root + path for path in _COMMON_SITEMAP_PATHS]

        seen_sitemaps: set[str] = set()
        queue = list(candidates)
        seen_urls: set[str] = set()

        while queue and len(seen_sitemaps) < max_sitemaps and len(seen_urls) < max_urls:
            sitemap_url = queue.pop(0)
            if sitemap_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sitemap_url)

            xml = _fetch(client, sitemap_url)
            if xml is None:
                continue

            site_map.sitemap_urls.append(sitemap_url)

            nested, page_urls = _parse_sitemap_xml(xml)
            for nested_url in nested:
                if nested_url not in seen_sitemaps:
                    queue.append(nested_url)

            for page_url in page_urls:
                if page_url not in seen_urls:
                    seen_urls.add(page_url)
                    site_map.urls.append(page_url)
                    if len(seen_urls) >= max_urls:
                        break

    return site_map


def _sitemaps_from_robots(client: httpx.Client, root: str) -> list[str]:
    robots_url = urljoin(root, "/robots.txt")
    text = _fetch(client, robots_url)
    if text is None:
        return []
    return _SITEMAP_RE.findall(text)


def _fetch(client: httpx.Client, url: str) -> str | None:
    try:
        resp = client.get(url)
        if resp.status_code >= 400:
            return None
        return resp.text
    except httpx.HTTPError as exc:
        logger.debug("Failed to fetch %s: %s", url, exc)
        return None


def _parse_sitemap_xml(xml: str) -> tuple[list[str], list[str]]:
    """Parse a sitemap XML document. Returns (nested_sitemap_urls, page_urls).

    Handles both ``<urlset>`` (page listing) and ``<sitemapindex>``
    (listing of other sitemaps) per the sitemaps.org schema.
    """
    tree = HTMLParser(xml)

    nested = [node.text(strip=True) for node in tree.css("sitemapindex sitemap loc")]
    pages = [node.text(strip=True) for node in tree.css("urlset url loc")]

    if not nested and not pages:
        # Fallback: some sitemaps omit namespacing in ways selectolax's
        # CSS engine won't match; do a generic <loc> sweep and bucket by
        # whether the document looks like an index.
        locs = [node.text(strip=True) for node in tree.css("loc")]
        if "<sitemapindex" in xml.lower():
            nested = locs
        else:
            pages = locs

    nested = [u for u in nested if u]
    pages = [u for u in pages if u]
    return nested, pages
