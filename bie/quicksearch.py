"""
``bie.search()`` and ``bie.websearch()`` — the simplest entry points.

.. code-block:: python

    import bie

    # Search specific sites you already know about
    results = bie.search("AI regulation news 2026", urls=["https://example.com/news"])

    # Search the live internet — no URLs, no API key, no subscription
    results = bie.websearch("latest AI regulation news 2026")
    for r in results:
        print(r.title, r.url)
        print(r.snippet)
"""

from __future__ import annotations

import re

from bie.config import BIESettings
from bie.discovery import discover_urls, discover_urls_multi
from bie.engine import BIE
from bie.models import SearchResult
from bie.query_expansion import generate_query_variants
from bie.security import scan_for_prompt_injection


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


def websearch(
    query: str,
    top_k: int = 10,
    discovery_results: int = 8,
    deep: bool = True,
    fanout: bool = True,
    max_query_variants: int = 3,
    scan_security: bool = True,
    **settings_kwargs,
) -> list[SearchResult]:
    """Search the **live internet** for ``query`` — no seed URLs, no API
    key, no subscription required.

    This is BIE's primary entry point — a "type a question, get a
    real-time answer" experience:

      1. **Discovery** — find candidate URLs for ``query`` using free,
         public, no-key search endpoints (DuckDuckGo, with a Bing
         fallback). When ``fanout=True`` (default), several phrasings of
         the query are searched and merged
         (:func:`bie.discovery.discover_urls_multi`), improving recall on
         ambiguous or multi-part questions.
      2. **Crawl + rank** — the discovered URLs are crawled with
         Bitscrape, their text extracted and chunked, and ranked against
         ``query`` using BIE's hybrid BM25 + vector index.
      3. **Security scan** — when ``scan_security=True`` (default), the
         specific chunk matched for each result is scanned for
         prompt-injection patterns via :mod:`bie.security`, and results
         whose matched text is itself flagged are dropped. This is a
         narrow heuristic safety net, not a guarantee — see
         :mod:`bie.security` for details and use
         :func:`bie.extract.extract` (which returns a full
         ``SecurityReport``) for page-level analysis.

    Args:
        query: The natural-language search query.
        top_k: Number of results to return.
        discovery_results: How many candidate URLs to discover per query
            variant before crawling.
        deep: If True (default), crawl discovered URLs with Bitscrape and
            rank the extracted page text via BIE's hybrid index — gives
            full-page snippets and proper relevance scoring. If False,
            skip crawling and return the raw discovery order with empty
            snippets (fast, but low quality — mainly useful for debugging
            discovery itself).
        fanout: If True (default), search multiple phrasings of ``query``
            (see :func:`bie.query_expansion.generate_query_variants`) and
            merge results for better recall. Set False for a single,
            faster lookup.
        max_query_variants: Maximum number of query phrasings to use when
            ``fanout=True``.
        scan_security: If True (default), filter out results whose
            matched chunk text trips the prompt-injection heuristics in
            :mod:`bie.security`.
        **settings_kwargs: Forwarded to :class:`bie.config.BIESettings`
            (e.g. ``max_pages=1``, ``use_embeddings=False``,
            ``request_timeout=10``).

    Example::

        import bie
        results = bie.websearch("who won the latest F1 race")
        for r in results:
            print(r.title, "-", r.url)
            print(r.snippet)
    """
    if fanout and max_query_variants > 1:
        variants = generate_query_variants(query, max_variants=max_query_variants)
        urls = discover_urls_multi(
            variants,
            max_results_per_query=discovery_results,
            max_total=discovery_results * max_query_variants,
        )
    else:
        urls = discover_urls(query, max_results=discovery_results)

    if not urls:
        return []

    if not deep:
        return [
            SearchResult(
                title=url,
                url=url,
                snippet="",
                source=_domain(url),
                score=1.0 / (i + 1),
            )
            for i, url in enumerate(urls[:top_k])
        ]

    settings_kwargs.setdefault("max_pages", 1)
    settings_kwargs.setdefault("max_depth", 0)
    engine = BIE(BIESettings(**settings_kwargs))
    fetch_k = top_k * 2 if scan_security else top_k
    results = engine.search_web(query, urls, top_k=fetch_k)

    if results:
        if scan_security:
            results = _filter_injection_only_results(engine, results)
        return results[:top_k]

    # Fallback: crawling produced nothing usable (e.g. all JS-rendered
    # pages, or every page failed/blocked) — return discovered URLs
    # without snippets rather than an empty list, so the caller still
    # gets *something* to work with.
    return [
        SearchResult(
            title=url,
            url=url,
            snippet="",
            source=_domain(url),
            score=1.0 / (i + 1),
        )
        for i, url in enumerate(urls[:top_k])
    ]


def _filter_injection_only_results(engine: BIE, results: list[SearchResult]) -> list[SearchResult]:
    """Drop results whose matched chunk is itself flagged as containing
    prompt-injection patterns.

    This is a narrow heuristic: the check only runs on the specific
    matched chunk (not the whole page), keeping the false-positive rate
    low for legitimate pages that merely *discuss* prompt injection. It
    is not a comprehensive content-safety filter — see
    :mod:`bie.security`.
    """
    filtered: list[SearchResult] = []
    for result in results:
        chunk = engine.index.chunks.get(result.chunk_id) if result.chunk_id else None
        if chunk:
            report = scan_for_prompt_injection(chunk.text)
            if report.flagged:
                continue
        filtered.append(result)
    return filtered


def _domain(url: str) -> str:
    m = re.match(r"https?://([^/]+)/?", url)
    return m.group(1) if m else url
