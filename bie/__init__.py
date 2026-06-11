"""
BIE — BitSearch Intelligence Engine
=====================================

The fastest, simplest way to give any LLM, RAG pipeline, or AI agent
real-time, citation-backed web search and extraction.

Built on top of **Bitscrape** (https://pypi.org/project/bitscrape/) —
BIE adds a hybrid (keyword + semantic) search index, a clean Python API,
a REST server, a CLI, and a Model Context Protocol (MCP) tool so any
AI application can call ``search()`` and get fresh, ranked, cited results.

Quick start
-----------

.. code-block:: python

    import bie

    # One-shot: crawl + index + search, all in memory
    results = bie.search("latest semiconductor export rules 2026", urls=[
        "https://www.reuters.com/technology/",
        "https://www.bloomberg.com/technology",
    ])

    for r in results:
        print(r.title, r.url, r.score)

Or build a persistent index you can query repeatedly::

    engine = bie.BIE()
    engine.crawl(["https://example.com"])
    hits = engine.search("example query", top_k=5)

Run as a server::

    bie serve --port 8000

Run as an MCP tool (for Claude Desktop, Claude Code, etc.)::

    bie mcp
"""

from __future__ import annotations

from bie.config import BIESettings
from bie.engine import BIE
from bie.models import Document, SearchResult
from bie.quicksearch import search

__version__ = "0.1.0"

__all__ = [
    "BIE",
    "BIESettings",
    "Document",
    "SearchResult",
    "search",
    "__version__",
]
