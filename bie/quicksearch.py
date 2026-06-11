"""
``bie.search()`` — the simplest possible entry point.

.. code-block:: python

    import bie
    results = bie.search("AI regulation news 2026", urls=["https://example.com/news"])
"""

from __future__ import annotations

from bie.config import BIESettings
from bie.engine import BIE
from bie.models import SearchResult


def search(
    query: str,
    urls: list[str],
    top_k: int = 10,
    **settings_kwargs,
) -> list[SearchResult]:
    """Crawl ``urls`` and return the top-``top_k`` results for ``query``.

    This spins up a fresh, in-memory :class:`bie.BIE` instance — convenient
    for scripts and one-off queries. For repeated queries against the same
    sources, create a :class:`bie.BIE` instance and reuse it instead.

    Args:
        query: The search query.
        urls: Seed URLs to crawl.
        top_k: Number of results to return.
        **settings_kwargs: Forwarded to :class:`bie.config.BIESettings`
            (e.g. ``max_pages=10``, ``use_embeddings=False``).
    """
    engine = BIE(BIESettings(**settings_kwargs))
    return engine.search_web(query, urls, top_k=top_k)
