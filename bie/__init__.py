"""
BIE — BitSearch Intelligence Engine
=====================================

A real-time web search engine and crawling toolkit for AI applications —
built on top of **Bitscrape** (https://pypi.org/project/bitscrape/). No
API keys, no subscriptions, no third-party search services.

Core primitives
----------------

- :func:`websearch` — search the live internet for a query (no URLs needed)
- :func:`search` — crawl + rank specific URLs against a query
- :func:`extract` — get clean Markdown from a single URL
- :func:`map_site` — discover a site's sitemap before crawling
- :func:`crawl_site` — crawl a site guided by a natural-language instruction
- :class:`BIE` — build a persistent, queryable index

Quick start
-----------

.. code-block:: python

    import bie

    # Search the live internet — no URLs, no API key, no subscription
    results = bie.websearch("who won the latest F1 race")
    for r in results:
        print(r.title, r.url)
        print(r.snippet)

    # Get clean markdown from a specific page
    page = bie.extract("https://example.com/article")
    print(page.markdown)

    # Discover a site's structure before crawling
    sitemap = bie.map_site("https://example.com")
    print(sitemap.urls[:10])

    # Crawl a site guided by an instruction
    engine, results = bie.crawl_site(
        ["https://docs.example.com"],
        instruction="authentication and rate limits",
    )

Run as a server::

    bie serve --port 8000

Run as an MCP tool (for Claude Desktop, Claude Code, etc.)::

    bie mcp
"""

from __future__ import annotations

from importlib import metadata as _metadata

from bie.config import BIESettings
from bie.engine import BIE
from bie.extract import ExtractError, ExtractResult, extract
from bie.models import Document, SearchResult
from bie.quicksearch import search, websearch
from bie.security import SecurityFinding, SecurityReport, scan_for_prompt_injection
from bie.sitecrawl import crawl_site
from bie.sitemap import SiteMap, map_site

try:
    # Reflects the version actually installed (matches PyPI/pyproject.toml).
    __version__ = _metadata.version("bits-bie")
except _metadata.PackageNotFoundError:
    # Editable/source checkout without installed metadata.
    __version__ = "1.2.4"

__all__ = [
    "BIE",
    "BIESettings",
    "Document",
    "SearchResult",
    "search",
    "websearch",
    "extract",
    "ExtractResult",
    "ExtractError",
    "map_site",
    "SiteMap",
    "crawl_site",
    "scan_for_prompt_injection",
    "SecurityReport",
    "SecurityFinding",
    "__version__",
]
